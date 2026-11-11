// Modified from abg-OAI/codex: module import path changed for this extraction.
// Package cli parses layerctl commands and renders their results. Domain
// packages own projection, layer, and upstream behavior.
package cli

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"strings"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/graph"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/layer"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/projection"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/upstream"
)

// Run executes one layerctl invocation from the repository containing the
// current directory.
func Run(ctx context.Context, args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: layerctl projection <create|list|path|checkout|delete> ...")
	}
	workingDirectory, err := os.Getwd()
	if err != nil {
		return fmt.Errorf("get working directory: %w", err)
	}
	git, err := gitrepo.Discover(ctx, workingDirectory)
	if err != nil {
		return fmt.Errorf("discover Git repository: %w", err)
	}
	canonical, err := definition.Load(git.Root)
	if err != nil {
		return fmt.Errorf("load canonical definition: %w", err)
	}
	if args[0] == "graph" {
		flags := flag.NewFlagSet("graph", flag.ContinueOnError)
		flags.SetOutput(stderr)
		format := flags.String("format", "dot", "graph output format: dot or mermaid")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if flags.NArg() != 0 {
			return errors.New("usage: layerctl graph [--format dot|mermaid]")
		}
		return graph.Write(stdout, canonical.Layers, *format)
	}
	if canonical.Upstream.Tag == "" {
		return runComposition(ctx, canonical, git, args, stdout, stderr)
	}
	// Legacy execution must also skip disabled layers. Keep all definitions
	// for the explicit migrate command so disabled layers remain migratable.
	if !(len(args) > 1 && args[0] == "layer" && args[1] == "migrate") {
		active := *canonical
		active.Layers = nil
		for _, unit := range canonical.Layers {
			if !unit.Disabled {
				active.Layers = append(active.Layers, unit)
			}
		}
		canonical = &active
	}
	service := &projection.Service{
		Definition: canonical,
		Git:        git,
		Log:        log.New(stderr, "layerctl: ", 0),
	}
	switch args[0] {
	case "projection":
		return runProjection(ctx, service, args[1:], stdout, stderr)
	case "layer":
		layers := &layer.Service{Definition: canonical, Git: git, Projection: service}
		return runLayer(ctx, layers, args[1:], stderr)
	case "upstream":
		upstreamService := &upstream.Service{Definition: canonical, Git: git, Projection: service}
		return runUpstream(ctx, upstreamService, args[1:], stdout, stderr)
	case "check":
		if len(args) != 1 {
			return errors.New("usage: layerctl check")
		}
		upstreamService := &upstream.Service{Definition: canonical, Git: git, Projection: service}
		return upstreamService.Check(ctx)
	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}

func runUpstream(ctx context.Context, service *upstream.Service, args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: layerctl upstream <advance|continue|abort> ...")
	}
	switch args[0] {
	case "advance":
		if len(args) < 2 || strings.HasPrefix(args[1], "-") {
			return errors.New("usage: layerctl upstream advance RUST_TAG [--worktree PATH]")
		}
		flags := flag.NewFlagSet("upstream advance", flag.ContinueOnError)
		flags.SetOutput(stderr)
		worktree := flags.String("worktree", "", "use PATH for conflict resolution")
		if err := flags.Parse(args[2:]); err != nil {
			return err
		}
		if flags.NArg() != 0 {
			return errors.New("usage: layerctl upstream advance RUST_TAG [--worktree PATH]")
		}
		path, err := service.Advance(ctx, upstream.AdvanceRequest{Tag: args[1], WorktreePath: *worktree})
		if path != "" {
			fmt.Fprintln(stdout, path)
		}
		return err
	case "continue":
		if len(args) != 1 {
			return errors.New("usage: layerctl upstream continue")
		}
		path, err := service.Continue(ctx)
		if path != "" {
			fmt.Fprintln(stdout, path)
		}
		return err
	case "abort":
		if len(args) != 1 {
			return errors.New("usage: layerctl upstream abort")
		}
		return service.Abort(ctx)
	default:
		return fmt.Errorf("unknown upstream command %q", args[0])
	}
}

func runLayer(ctx context.Context, service *layer.Service, args []string, stderr io.Writer) error {
	if len(args) < 2 {
		return errors.New("usage: layerctl layer <add|refresh|migrate> ...")
	}
	id := args[1]
	if args[0] == "migrate" {
		if len(args) != 2 {
			return errors.New("usage: layerctl layer migrate ID")
		}
		return service.Migrate(id)
	}
	flags := flag.NewFlagSet("layer "+args[0], flag.ContinueOnError)
	flags.SetOutput(stderr)
	from := flags.String("from", "", "capture from PROJECTION")
	switch args[0] {
	case "add":
		if err := flags.Parse(args[2:]); err != nil {
			return err
		}
		if flags.NArg() != 0 || *from == "" {
			return errors.New("usage: layerctl layer add NNNN-LAYER-SLUG --from PROJECTION")
		}
		return service.Add(ctx, layer.AddRequest{ID: id, Projection: *from})
	case "refresh":
		if err := flags.Parse(args[2:]); err != nil {
			return err
		}
		if flags.NArg() != 0 || *from == "" {
			return errors.New("usage: layerctl layer refresh ID --from PROJECTION")
		}
		return service.Refresh(ctx, id, *from)
	default:
		return fmt.Errorf("unknown layer command %q", args[0])
	}
}

type projectionRunner interface {
	Create(context.Context, projection.CreateRequest) (projection.Projection, error)
	List(context.Context) ([]projection.Projection, error)
	Path(context.Context, string) (string, error)
	Delete(context.Context, string) error
}

func runProjection(ctx context.Context, service projectionRunner, args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: layerctl projection <create|list|path|checkout|delete> ...")
	}
	switch args[0] {
	case "create":
		return runProjectionCreate(ctx, service, args[1:], stdout, stderr)
	case "list":
		if len(args) != 1 {
			return errors.New("usage: layerctl projection list")
		}
		projections, err := service.List(ctx)
		if err != nil {
			return err
		}
		for _, item := range projections {
			fmt.Fprintf(stdout, "%s\t%s\t%s\t%s\n", item.Name, item.Base, item.Head, item.WorktreePath)
		}
		return nil
	case "path":
		if len(args) != 2 {
			return errors.New("usage: layerctl projection path NAME")
		}
		path, err := service.Path(ctx, args[1])
		if err != nil {
			return err
		}
		fmt.Fprintln(stdout, path)
		return nil
	case "checkout":
		return runProjectionCheckout(ctx, service, args[1:], stdout, stderr)
	case "delete":
		if len(args) != 2 {
			return errors.New("usage: layerctl projection delete NAME")
		}
		return service.Delete(ctx, args[1])
	default:
		return fmt.Errorf("unknown projection command %q", args[0])
	}
}

func runProjectionCreate(ctx context.Context, service projectionRunner, args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 || strings.HasPrefix(args[0], "-") {
		return errors.New("usage: layerctl projection create NAME [--worktree PATH] [--through LAYER]")
	}
	flags := flag.NewFlagSet("projection create", flag.ContinueOnError)
	flags.SetOutput(stderr)
	worktree := flags.String("worktree", "", "attach the projection at PATH")
	through := flags.String("through", "", "stop after LAYER")
	if err := flags.Parse(args[1:]); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return errors.New("usage: layerctl projection create NAME [--worktree PATH] [--through LAYER]")
	}
	created, err := service.Create(ctx, projection.CreateRequest{
		Name:         args[0],
		WorktreePath: *worktree,
		Through:      *through,
	})
	if err != nil {
		return err
	}
	if created.WorktreePath != "" {
		fmt.Fprintln(stdout, created.WorktreePath)
	} else {
		fmt.Fprintf(stdout, "refs/layerctl/projections/%s/head\n", created.Name)
	}
	return nil
}

func runProjectionCheckout(ctx context.Context, service projectionRunner, args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 || strings.HasPrefix(args[0], "-") {
		return errors.New("usage: layerctl projection checkout NAME --worktree PATH")
	}
	flags := flag.NewFlagSet("projection checkout", flag.ContinueOnError)
	flags.SetOutput(stderr)
	worktree := flags.String("worktree", "", "attach the projection at PATH")
	if err := flags.Parse(args[1:]); err != nil {
		return err
	}
	if flags.NArg() != 0 || *worktree == "" {
		return errors.New("usage: layerctl projection checkout NAME --worktree PATH")
	}
	checkout, ok := service.(interface {
		Checkout(context.Context, projection.CheckoutRequest) (string, error)
	})
	if !ok {
		return errors.New("composition projections are already checked out; use projection path")
	}
	path, err := checkout.Checkout(ctx, projection.CheckoutRequest{
		Name:         args[0],
		WorktreePath: *worktree,
	})
	if err != nil {
		return err
	}
	fmt.Fprintln(stdout, path)
	return nil
}

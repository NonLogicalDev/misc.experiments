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
	"os"
	"strings"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/graph"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/layer"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/projection"
)

// Run executes one layerctl invocation from the repository containing the
// current directory.
func Run(ctx context.Context, args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: layerctl projection <create|list|path|continue|unlock|delete> ...")
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
	return runComposition(ctx, canonical, git, args, stdout, stderr)
}

func runLayer(ctx context.Context, service *layer.Service, args []string, stderr io.Writer) error {
	if len(args) < 2 {
		return errors.New("usage: layerctl layer <add|refresh> ...")
	}
	id := args[1]
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
		return errors.New("usage: layerctl projection <create|list|path|continue|unlock|delete> ...")
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
	fmt.Fprintln(stdout, created.WorktreePath)
	return nil
}

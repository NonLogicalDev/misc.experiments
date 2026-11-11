// Composition mode uses clone operations rather than a special upstream.
package cli

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/layer"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/projection"
)

func runComposition(ctx context.Context, canonical *definition.Repository, git *gitrepo.Repository, args []string, stdout, stderr io.Writer) error {
	service := &projection.CompositionService{Definition: canonical, Git: git, Log: log.New(stderr, "layerctl: ", 0)}
	switch args[0] {
	case "projection":
		if len(args) > 1 && args[1] == "unlock" {
			if len(args) != 3 {
				return errors.New("usage: layerctl projection unlock NAME")
			}
			return service.Unlock(ctx, args[2])
		}
		if len(args) > 1 && args[1] == "continue" {
			if len(args) != 3 {
				return errors.New("usage: layerctl projection continue NAME")
			}
			result, err := service.Continue(ctx, args[2])
			if result.WorktreePath != "" {
				fmt.Fprintln(stdout, result.WorktreePath)
			}
			return err
		}
		return runProjection(ctx, service, args[1:], stdout, stderr)
	case "layer":
		layers := &layer.Service{Definition: canonical, Git: git, Projection: service}
		if len(args) > 2 && args[1] == "refresh" {
			for _, unit := range canonical.Layers {
				if unit.ID != args[2] || unit.Message == nil {
					continue
				}
				flags := flag.NewFlagSet("layer refresh", flag.ContinueOnError)
				flags.SetOutput(stderr)
				from := flags.String("from", "", "capture from projection")
				if err := flags.Parse(args[3:]); err != nil {
					return err
				}
				if flags.NArg() != 0 || *from == "" {
					return errors.New("usage: layerctl layer refresh ID --from PROJECTION")
				}
				return layers.RefreshComposition(ctx, unit.ID, *from, service)
			}
		}
		return runLayer(ctx, layers, args[1:], stderr)
	case "check":
		if len(args) != 1 {
			return errors.New("usage: layerctl check")
		}
		f, err := os.CreateTemp("", "layerctl-check-")
		if err != nil {
			return err
		}
		name := strings.ToLower(filepath.Base(f.Name()))
		if err := f.Close(); err != nil {
			return err
		}
		_ = os.Remove(f.Name())
		_, err = service.Create(ctx, projection.CreateRequest{Name: name})
		if err != nil {
			return fmt.Errorf("check composition: %w", err)
		}
		if err := service.Delete(ctx, name); err != nil {
			return fmt.Errorf("remove check projection: %w", err)
		}
		return nil
	case "upstream":
		return errors.New("composition mode has no special upstream; change git-clone operations in layer.toml")
	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}

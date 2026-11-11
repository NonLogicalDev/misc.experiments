// Modified from abg-OAI/codex: adds manifest operation support.
package layercommit

import (
	"fmt"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
)

// normalizedUnit retains the original single Git apply operation, which stages
// clean overlay additions even if a patch conflicts during upstream advance.
func normalizedUnit(unit definition.Unit) (definition.Unit, error) {
	if unit.Message == nil {
		return unit, nil
	}
	seenPatch, seenOverlay := false, false
	for _, op := range unit.Operations {
		switch op.Kind {
		case "patch":
			if seenPatch || seenOverlay {
				return definition.Unit{}, fmt.Errorf("layer %q: only one patch before an overlay is supported", unit.ID)
			}
			seenPatch = true
			unit.PatchPath = op.Path
		case "overlay":
			if seenOverlay {
				return definition.Unit{}, fmt.Errorf("layer %q: only one overlay is supported", unit.ID)
			}
			seenOverlay = true
			unit.Overlay = op.Overlay
		default:
			return definition.Unit{}, fmt.Errorf("layer %q: unsupported operation %q", unit.ID, op.Kind)
		}
	}
	return unit, nil
}

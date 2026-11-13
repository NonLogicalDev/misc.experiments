// Package projection materializes and manages composed workspaces.
package projection

import (
	"fmt"
	"regexp"
)

var namePattern = regexp.MustCompile(`^[a-z0-9][a-z0-9-]*$`)

// CreateRequest selects a projection and an optional terminal layer.
type CreateRequest struct{ Name, WorktreePath, Through string }

// Projection is the current state of a named workspace.
type Projection struct{ Name, Base, Head, WorktreePath string }

func parseName(raw string) (string, error) {
	if !namePattern.MatchString(raw) {
		return "", fmt.Errorf("invalid projection name %q", raw)
	}
	return raw, nil
}

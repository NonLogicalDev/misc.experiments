package cli

import (
	"bytes"
	"strings"
	"testing"
)

func TestProjectionCreateRequiresNameBeforeFlags(t *testing.T) {
	var stdout bytes.Buffer
	var stderr bytes.Buffer

	err := runProjectionCreate(t.Context(), nil, []string{"--worktree", "/tmp/example"}, &stdout, &stderr)
	if err == nil || !strings.Contains(err.Error(), "projection create NAME") {
		t.Fatalf("runProjectionCreate() error = %v", err)
	}
}

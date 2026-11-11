package layer

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/layercommit"
)

func TestManifestWritersPreserveMultilineCommitMessages(t *testing.T) {
	messages := map[string]string{
		"trailing newline":                       "A subject\n",
		"no trailing newline":                    "A subject",
		"leading and multiple trailing newlines": "\nsubject\n\n",
		"quotes and hashes":                      "A \"\"\"quoted\"\"\" # subject\n# body\n",
		"backslashes":                            "literal \\n and a slash at end \\\nnext\\",
		"controls and unicode":                   "tab\treturn\rdelete\x7f snowman ☃\n",
	}
	for name, message := range messages {
		for _, writer := range []string{"capture", "refresh"} {
			t.Run(name+"/"+writer, func(t *testing.T) {
				dir := t.TempDir()
				var err error
				if writer == "capture" {
					err = writeManifestLayer(dir, layercommit.Captured{Message: []byte(message)}, nil)
				} else {
					err = refreshWriteManifest(dir, definition.Unit{Directory: dir}, []byte(message), "")
				}
				if err != nil {
					t.Fatal(err)
				}
				raw, err := os.ReadFile(filepath.Join(dir, "layer.toml"))
				if err != nil {
					t.Fatal(err)
				}
				if !strings.Contains(string(raw), "commit-msg = \"\"\"\n") {
					t.Fatalf("expected multiline TOML message: %s", raw)
				}
				unit, err := definition.LoadUnit("0001-test", dir)
				if err != nil {
					t.Fatalf("load generated manifest: %v\n%s", err, raw)
				}
				if string(unit.Message) != message {
					t.Fatalf("message = %q, want %q", unit.Message, message)
				}
				if refreshHasTOMLComment(raw) {
					t.Fatalf("generated manifest incorrectly treated as commented: %s", raw)
				}
			})
		}
	}
}

func TestManifestWritersPreserveExplicitEmptyDependencies(t *testing.T) {
	for _, writer := range []string{"capture", "refresh"} {
		t.Run(writer, func(t *testing.T) {
			dir := t.TempDir()
			metadata := definition.Unit{Directory: dir, DependsOn: []string{}}
			var err error
			if writer == "capture" {
				err = writeManifestLayer(dir, layercommit.Captured{Message: []byte("Message\n")}, &metadata)
			} else {
				err = refreshWriteManifest(dir, metadata, []byte("Message\n"), "")
			}
			if err != nil {
				t.Fatal(err)
			}
			unit, err := definition.LoadUnit("0001-test", dir)
			if err != nil {
				t.Fatal(err)
			}
			if unit.DependsOn == nil || len(unit.DependsOn) != 0 {
				t.Fatalf("explicit empty depends-on lost: %#v", unit.DependsOn)
			}
		})
	}
}

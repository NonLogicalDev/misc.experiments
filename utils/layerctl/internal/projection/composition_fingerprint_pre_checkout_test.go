package projection

import (
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
)

func TestFingerprintWithoutClonePreCheckoutPatchRemainsCompatible(t *testing.T) {
	unit := definition.Unit{ID: "0001-base", Message: []byte("message"), Operations: []definition.Operation{{Kind: "git-clone", URL: "repo"}}}
	got, err := fingerprintUnits([]definition.Unit{unit})
	if err != nil {
		t.Fatal(err)
	}
	// This is the fingerprint representation used before pre-checkout patches.
	previous := `[{"AssetDigest":"","ID":"0001-base","Message":"bWVzc2FnZQ==","Operations":[{"Kind":"git-clone","URL":"repo","Dir":"","Ref":"","Commit":"","Args":null,"Depth":0,"Patch":null,"Overlay":null}],"DependsOn":null,"CoAuthors":null}]`
	want := fmt.Sprintf("%x", sha256.Sum256([]byte(previous)))
	if got != want {
		t.Fatalf("fingerprint = %s, want %s", got, want)
	}
}

func TestFingerprintIncludesClonePreCheckoutPatchIdentityAndContents(t *testing.T) {
	dir := t.TempDir()
	a, b := filepath.Join(dir, "a.patch"), filepath.Join(dir, "b.patch")
	if err := os.WriteFile(a, []byte("first"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(b, []byte("first"), 0644); err != nil {
		t.Fatal(err)
	}
	unit := definition.Unit{ID: "0001-base", Directory: dir, Message: []byte("message"), Operations: []definition.Operation{{Kind: "git-clone", URL: "repo", PreCheckoutPatch: a}}}
	original, err := fingerprintUnits([]definition.Unit{unit})
	if err != nil {
		t.Fatal(err)
	}
	unit.Operations[0].PreCheckoutPatch = b
	differentPath, err := fingerprintUnits([]definition.Unit{unit})
	if err != nil {
		t.Fatal(err)
	}
	if original == differentPath {
		t.Fatal("same-content path change did not change fingerprint")
	}
	unit.Operations[0].PreCheckoutPatch = a
	if err := os.WriteFile(a, []byte("second"), 0644); err != nil {
		t.Fatal(err)
	}
	differentContents, err := fingerprintUnits([]definition.Unit{unit})
	if err != nil {
		t.Fatal(err)
	}
	if original == differentContents {
		t.Fatal("patch content change did not change fingerprint")
	}
	if err := os.Remove(a); err != nil {
		t.Fatal(err)
	}
	if _, err := fingerprintUnits([]definition.Unit{unit}); err == nil {
		t.Fatal("missing patch accepted")
	}
}

func TestFingerprintIncludesClonePreCheckoutScriptAndAssets(t *testing.T) {
	dir := t.TempDir()
	a, b := filepath.Join(dir, "a"), filepath.Join(dir, "b")
	asset := filepath.Join(dir, "support")
	for _, f := range []string{a, b} {
		if err := os.WriteFile(f, []byte("same"), 0755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(asset, []byte("first"), 0644); err != nil {
		t.Fatal(err)
	}
	unit := definition.Unit{ID: "0001-base", Directory: dir, Message: []byte("message"), Operations: []definition.Operation{{Kind: "git-clone", URL: "repo", PreCheckoutScript: a}}}
	original, err := fingerprintUnits([]definition.Unit{unit})
	if err != nil {
		t.Fatal(err)
	}
	unit.Operations[0].PreCheckoutScript = b
	changedPath, err := fingerprintUnits([]definition.Unit{unit})
	if err != nil {
		t.Fatal(err)
	}
	if original == changedPath {
		t.Fatal("same-content script path did not change fingerprint")
	}
	unit.Operations[0].PreCheckoutScript = a
	if err := os.WriteFile(asset, []byte("second"), 0644); err != nil {
		t.Fatal(err)
	}
	changedAsset, err := fingerprintUnits([]definition.Unit{unit})
	if err != nil {
		t.Fatal(err)
	}
	if original == changedAsset {
		t.Fatal("support asset change did not change fingerprint")
	}
	if err := os.WriteFile(asset, []byte("first"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(a, []byte("other"), 0755); err != nil {
		t.Fatal(err)
	}
	changedScript, err := fingerprintUnits([]definition.Unit{unit})
	if err != nil {
		t.Fatal(err)
	}
	if original == changedScript {
		t.Fatal("script content change did not change fingerprint")
	}
}

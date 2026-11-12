package layer

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"unicode/utf8"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/commitauthors"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/projection"
)

// RefreshComposition retains a manifest layer's complete operation list and
// records committed edits as an additional patch. Candidate replay must match
// the edited tree and message and preserve imported ancestry. Replay executes
// scripts again, so their external side effects cannot be rolled back.
func (s *Service) RefreshComposition(ctx context.Context, id, projectionName string, composer *projection.CompositionService) error {
	if err := definition.ValidateLayerID(id); err != nil {
		return err
	}
	index := -1
	for i, unit := range s.Definition.Layers {
		if unit.ID == id {
			index = i
			break
		}
	}
	if index < 0 {
		return fmt.Errorf("layer %q does not exist", id)
	}
	original := s.Definition.Layers[index]
	if original.Disabled {
		return fmt.Errorf("cannot refresh disabled layer %q", id)
	}
	activeIndex := 0
	for _, unit := range s.Definition.Layers[:index] {
		if !unit.Disabled {
			activeIndex++
		}
	}
	manifestBytes, err := os.ReadFile(filepath.Join(original.Directory, "layer.toml"))
	if err != nil {
		return fmt.Errorf("read original manifest: %w", err)
	}
	// The TOML decoder cannot retain comments. Refuse uncertain input rather
	// than silently dropping user text when rewriting the manifest.
	if refreshHasTOMLComment(manifestBytes) {
		return fmt.Errorf("cannot refresh a manifest with comments because they cannot be preserved")
	}
	currentUnit, err := definition.LoadUnit(id, original.Directory)
	if err != nil {
		return fmt.Errorf("reload layer: %w", err)
	}
	if !reflect.DeepEqual(original, currentUnit) {
		return fmt.Errorf("layer %q changed since it was loaded", id)
	}
	if original.Message == nil {
		return fmt.Errorf("layer %q is not a manifest", id)
	}
	through, err := composer.Through(ctx, projectionName)
	if err != nil {
		return err
	}
	if through != id {
		return fmt.Errorf("projection %q was created through %q, not %q", projectionName, through, id)
	}
	source, err := composer.Get(ctx, projectionName)
	if err != nil {
		return err
	}
	if source.Base == source.Head {
		return fmt.Errorf("projection %q has no committed changes", projectionName)
	}
	git := &gitrepo.Repository{Root: source.WorktreePath}
	status, err := git.Output(ctx, source.WorktreePath, "status", "--porcelain=v1", "--untracked-files=all")
	if err != nil {
		return fmt.Errorf("inspect projection changes: %w", err)
	}
	if status != "" {
		return fmt.Errorf("projection %q has uncommitted changes", projectionName)
	}
	if err := git.Run(ctx, source.WorktreePath, "merge-base", "--is-ancestor", source.Base, source.Head); err != nil {
		return fmt.Errorf("projection HEAD is not descended from its generated base: %w", err)
	}
	message, err := commitMessage(git, ctx, source.WorktreePath, source.Head)
	if err != nil {
		return err
	}
	if len(message) == 0 || !utf8.Valid(message) || bytes.ContainsRune(message, 0) {
		return fmt.Errorf("commit message must be nonempty UTF-8 without NUL")
	}
	before, err := refreshDirectoryFingerprint(original.Directory)
	if err != nil {
		return err
	}
	root := filepath.Join(s.Definition.Root, "layers")
	candidateDir, err := os.MkdirTemp(root, ".layerctl-refresh-"+id+"-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(candidateDir)
	if err := refreshCopyDirectory(original.Directory, candidateDir); err != nil {
		return fmt.Errorf("copy layer: %w", err)
	}
	patch, err := git.Bytes(ctx, source.WorktreePath, "-c", "diff.suppressBlankEmpty=true", "diff-tree", "--patch", "--binary", "--full-index", "--no-commit-id", "-r", "--no-renames", "--no-ext-diff", "--no-textconv", "--no-color", "--diff-algorithm=myers", "--src-prefix=a/", "--dst-prefix=b/", source.Base, source.Head)
	if err != nil {
		return fmt.Errorf("capture projection diff: %w", err)
	}
	var patchName string
	if len(patch) > 0 {
		for n := 0; ; n++ {
			patchName = "refresh.patch"
			if n > 0 {
				patchName = fmt.Sprintf("refresh-%d.patch", n)
			}
			f, err := os.OpenFile(filepath.Join(candidateDir, patchName), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0644)
			if os.IsExist(err) {
				continue
			}
			if err != nil {
				return err
			}
			_, err = f.Write(patch)
			closeErr := f.Close()
			if err != nil {
				return err
			}
			if closeErr != nil {
				return closeErr
			}
			break
		}
	}
	if err := refreshWriteManifest(candidateDir, original, message, patchName); err != nil {
		return err
	}
	candidate, err := definition.LoadUnit(id, candidateDir)
	if err != nil {
		return fmt.Errorf("validate candidate layer: %w", err)
	}
	copyDef := *s.Definition
	copyDef.Layers = append([]definition.Unit(nil), s.Definition.Layers...)
	copyDef.Layers[index] = candidate
	copyComposer := *composer
	copyComposer.Definition = &copyDef
	var random [12]byte
	if _, err := rand.Read(random[:]); err != nil {
		return err
	}
	name := "refresh-verify-" + hex.EncodeToString(random[:])
	verified, err := copyComposer.Create(ctx, projection.CreateRequest{Name: name, Through: id})
	if err != nil {
		return fmt.Errorf("replay refreshed layer: %w", err)
	}
	defer copyComposer.Delete(context.Background(), name)
	candidateGit := &gitrepo.Repository{Root: verified.WorktreePath}
	sourceTree, err := git.Output(ctx, source.WorktreePath, "rev-parse", source.Head+"^{tree}")
	if err != nil {
		return err
	}
	candidateTree, err := candidateGit.Output(ctx, verified.WorktreePath, "rev-parse", verified.Head+"^{tree}")
	if err != nil {
		return err
	}
	if sourceTree != candidateTree {
		return fmt.Errorf("refreshed layer does not reproduce the accepted tree")
	}
	candidateMessage, err := commitMessage(candidateGit, ctx, verified.WorktreePath, verified.Head)
	if err != nil {
		return err
	}
	expectedMessage, err := commitauthors.Message(original, message)
	if err != nil {
		return err
	}
	if !bytes.Equal(expectedMessage, candidateMessage) {
		return fmt.Errorf("refreshed layer does not reproduce the accepted commit message with configured co-authors")
	}
	if err := refreshCompareHistory(ctx, git, candidateGit, source.Base, verified.Head, activeIndex); err != nil {
		return err
	}
	after, err := refreshDirectoryFingerprint(original.Directory)
	if err != nil {
		return err
	}
	if before != after {
		return fmt.Errorf("layer %q changed during refresh", id)
	}
	current, err := composer.Get(ctx, projectionName)
	if err != nil {
		return err
	}
	if current.Head != source.Head || current.Base != source.Base {
		return fmt.Errorf("projection changed during refresh")
	}
	status, err = git.Output(ctx, source.WorktreePath, "status", "--porcelain=v1", "--untracked-files=all")
	if err != nil {
		return err
	}
	if status != "" {
		return fmt.Errorf("projection gained uncommitted changes during refresh")
	}
	if err := copyComposer.Delete(ctx, name); err != nil {
		return fmt.Errorf("remove verification projection: %w", err)
	}
	return installLayer(root, id, candidateDir, true)
}

// refreshWriteManifest keeps the operation order and original paths; it only
// changes the message and appends the patch generated from the accepted edit.
func refreshWriteManifest(directory string, unit definition.Unit, message []byte, patchName string) error {
	var out strings.Builder
	quote := func(s string) string { b, _ := json.Marshal(s); return string(b) }
	if unit.Disabled || unit.DependsOn != nil {
		out.WriteString("[layer]\n")
		if unit.Disabled {
			out.WriteString("enabled = false\n")
		}
		if unit.DependsOn != nil {
			out.WriteString("depends-on = [")
			for i, id := range unit.DependsOn {
				if i > 0 {
					out.WriteString(", ")
				}
				out.WriteString(quote(id))
			}
			out.WriteString("]\n")
		}
		out.WriteString("\n")
	}
	fmt.Fprintf(&out, "[vcs]\ncommit-msg = %s\n", multilineMessage(string(message)))
	if len(unit.CoAuthors) > 0 {
		out.WriteString("co-authors = [")
		for i, author := range unit.CoAuthors {
			if i > 0 {
				out.WriteString(", ")
			}
			out.WriteString(quote(author))
		}
		out.WriteString("]\n")
	}
	for _, op := range unit.Operations {
		out.WriteString("\n[[operation]]\n")
		switch op.Kind {
		case "git-clone":
			fmt.Fprintf(&out, "[operation.git-clone]\nurl = %s\n", quote(op.URL))
			if op.Dir != "" {
				fmt.Fprintf(&out, "dir = %s\n", quote(op.Dir))
			}
			if op.PreCheckoutPatch != "" {
				rel, err := filepath.Rel(unit.Directory, op.PreCheckoutPatch)
				if err != nil {
					return err
				}
				fmt.Fprintf(&out, "pre-checkout-patch = %s\n", quote(filepath.ToSlash(rel)))
			}
			if op.PreCheckoutScript != "" {
				rel, err := filepath.Rel(unit.Directory, op.PreCheckoutScript)
				if err != nil {
					return err
				}
				fmt.Fprintf(&out, "pre-checkout-script = %s\n", quote(filepath.ToSlash(rel)))
			}
			if op.Ref != "" {
				fmt.Fprintf(&out, "ref = %s\n", quote(op.Ref))
			}
			if op.Commit != "" {
				fmt.Fprintf(&out, "commit = %s\n", quote(op.Commit))
			}
			if op.Depth != 0 {
				fmt.Fprintf(&out, "depth = %d\n", op.Depth)
			}
		case "patch", "overlay", "script":
			rel, err := filepath.Rel(unit.Directory, op.Path)
			if err != nil {
				return err
			}
			rel = filepath.ToSlash(rel)
			if op.Kind == "patch" {
				fmt.Fprintf(&out, "[operation.patch]\nfile = %s\n", quote(rel))
			} else if op.Kind == "overlay" {
				fmt.Fprintf(&out, "[operation.overlay]\ndirectory = %s\n", quote(rel))
			} else {
				fmt.Fprintf(&out, "[operation.script]\nfile = %s\n", quote(rel))
				if len(op.Args) > 0 {
					out.WriteString("args = [")
					for i, arg := range op.Args {
						if i > 0 {
							out.WriteString(", ")
						}
						out.WriteString(quote(arg))
					}
					out.WriteString("]\n")
				}
			}
		default:
			return fmt.Errorf("unsupported operation %q", op.Kind)
		}
	}
	if patchName != "" {
		fmt.Fprintf(&out, "\n[[operation]]\n[operation.patch]\nfile = %s\n", quote(patchName))
	}
	return os.WriteFile(filepath.Join(directory, "layer.toml"), []byte(out.String()), 0644)
}

// refreshCompareHistory compares source-parent IDs at every composed layer.
// Generated workspace commits have fresh metadata, so their IDs may differ.
func refreshCompareHistory(ctx context.Context, a, b *gitrepo.Repository, base, result string, index int) error {
	for i := index; i >= 0; i-- {
		left, err := refreshCommit(ctx, a, base)
		if err != nil {
			return err
		}
		right, err := refreshCommit(ctx, b, result)
		if err != nil {
			return err
		}
		start := 0
		if i > 0 {
			start = 1
		}
		if len(left.parents) < start || len(right.parents) < start || !equalStrings(left.parents[start:], right.parents[start:]) {
			return fmt.Errorf("imported source ancestry changed at layer %d", i)
		}
		if i < index && (left.tree != right.tree || !bytes.Equal(left.message, right.message)) {
			return fmt.Errorf("predecessor layer %d changed during refresh", i)
		}
		if i > 0 {
			base = left.parents[0]
			result = right.parents[0]
		}
	}
	return nil
}

type refreshCommitData struct {
	tree    string
	parents []string
	message []byte
}

func refreshCommit(ctx context.Context, git *gitrepo.Repository, commit string) (refreshCommitData, error) {
	data, err := git.Bytes(ctx, git.Root, "cat-file", "commit", commit)
	if err != nil {
		return refreshCommitData{}, err
	}
	head, message, ok := bytes.Cut(data, []byte("\n\n"))
	if !ok {
		return refreshCommitData{}, fmt.Errorf("invalid commit")
	}
	result := refreshCommitData{message: message}
	for _, line := range bytes.Split(head, []byte("\n")) {
		if bytes.HasPrefix(line, []byte("tree ")) {
			result.tree = string(line[5:])
		}
		if bytes.HasPrefix(line, []byte("parent ")) {
			result.parents = append(result.parents, string(line[7:]))
		}
	}
	if result.tree == "" {
		return result, fmt.Errorf("commit missing tree")
	}
	return result, nil
}
func equalStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func refreshCopyDirectory(src, dst string) error {
	return filepath.WalkDir(src, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		relative, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}
		if relative == "." {
			return nil
		}
		target := filepath.Join(dst, relative)
		info, err := os.Lstat(path)
		if err != nil {
			return err
		}
		switch {
		case info.IsDir():
			return os.Mkdir(target, info.Mode().Perm())
		case info.Mode()&os.ModeSymlink != 0:
			link, err := os.Readlink(path)
			if err != nil {
				return err
			}
			return os.Symlink(link, target)
		case info.Mode().IsRegular():
			input, err := os.Open(path)
			if err != nil {
				return err
			}
			defer input.Close()
			output, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, info.Mode().Perm())
			if err != nil {
				return err
			}
			_, err = io.Copy(output, input)
			closeErr := output.Close()
			if err != nil {
				return err
			}
			return closeErr
		default:
			return fmt.Errorf("unsupported layer input %q", relative)
		}
	})
}

func refreshDirectoryFingerprint(dir string) ([32]byte, error) {
	var data bytes.Buffer
	err := filepath.WalkDir(dir, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		rel, err := filepath.Rel(dir, path)
		if err != nil {
			return err
		}
		info, err := os.Lstat(path)
		if err != nil {
			return err
		}
		fmt.Fprintf(&data, "%d:%s:%d:", len(rel), rel, info.Mode())
		switch {
		case info.Mode().IsRegular():
			content, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			fmt.Fprintf(&data, "%d:", len(content))
			data.Write(content)
		case info.Mode()&os.ModeSymlink != 0:
			target, err := os.Readlink(path)
			if err != nil {
				return err
			}
			fmt.Fprintf(&data, "%d:%s", len(target), target)
		case !info.IsDir():
			return fmt.Errorf("unsupported layer input %q", rel)
		}
		return nil
	})
	return sha256.Sum256(data.Bytes()), err
}

// refreshHasTOMLComment ignores # characters inside TOML basic, literal, and
// multiline strings. The manifest has already been validated by LoadUnit.
func refreshHasTOMLComment(data []byte) bool {
	var quote byte
	multiline := false
	for i := 0; i < len(data); i++ {
		c := data[i]
		if quote == 0 {
			if c == '#' {
				return true
			}
			if c == '\'' || c == '"' {
				quote = c
				multiline = i+2 < len(data) && data[i+1] == c && data[i+2] == c
				if multiline {
					i += 2
				}
			}
			continue
		}
		if quote == '"' && c == '\\' {
			i++
			continue
		}
		if c == quote {
			if multiline {
				if i+2 < len(data) && data[i+1] == quote && data[i+2] == quote {
					for i+1 < len(data) && data[i+1] == quote {
						i++
					}
					quote = 0
					multiline = false
				}
			} else {
				quote = 0
			}
		}
	}
	return false
}

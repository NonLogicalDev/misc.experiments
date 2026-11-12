package operations

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
)

// DiffTrees returns a binary-safe patch between two Git trees.
func DiffTrees(ctx context.Context, git *gitrepo.Repository, before, after string) ([]byte, error) {
	patch, err := git.Bytes(
		ctx,
		git.Root,
		"-c", "diff.suppressBlankEmpty=true",
		"diff-tree",
		"--patch",
		"--binary",
		"--full-index",
		"--no-commit-id",
		"-r",
		"--no-renames",
		"--no-ext-diff",
		"--no-textconv",
		"--no-color",
		"--diff-algorithm=myers",
		"--src-prefix=a/",
		"--dst-prefix=b/",
		before,
		after,
	)
	if err != nil {
		return nil, fmt.Errorf("diff layer trees: %w", err)
	}
	return patch, nil
}

// TreeEntry identifies a file in a Git tree.
type TreeEntry struct {
	Path   string
	Mode   string
	Object string
}

// TreeEntries lists the leaves of a Git tree without modifying the worktree.
func TreeEntries(ctx context.Context, git *gitrepo.Repository, tree string) (map[string]TreeEntry, error) {
	output, err := git.Bytes(ctx, git.Root, "ls-tree", "-r", "-z", "--full-tree", tree)
	if err != nil {
		return nil, err
	}
	entries := make(map[string]TreeEntry)
	for record := range bytes.SplitSeq(output, []byte{0}) {
		if len(record) == 0 {
			continue
		}
		header, path, ok := strings.Cut(string(record), "\t")
		fields := strings.Fields(header)
		if !ok || len(fields) != 3 {
			return nil, fmt.Errorf("invalid Git tree record %q", record)
		}
		entries[path] = TreeEntry{Path: path, Mode: fields[0], Object: fields[2]}
	}
	return entries, nil
}

// EditTree constructs a tree with a private index. It never changes the
// caller's worktree or index; updates use Git's NUL-delimited index-info format.
func EditTree(ctx context.Context, git *gitrepo.Repository, base string, updates []byte) (string, error) {
	directory, err := os.MkdirTemp("", "layerctl-index-")
	if err != nil {
		return "", err
	}
	defer os.RemoveAll(directory)
	environment := []string{"GIT_INDEX_FILE=" + filepath.Join(directory, "index")}
	if base == "" {
		base = "--empty"
	}
	if _, err := git.Invoke(ctx, git.Root, gitrepo.Invocation{
		Arguments: []string{"read-tree", base}, Environment: environment,
	}); err != nil {
		return "", err
	}
	if len(updates) != 0 {
		if _, err := git.Invoke(ctx, git.Root, gitrepo.Invocation{
			Arguments: []string{"update-index", "-z", "--index-info"}, Stdin: updates, Environment: environment,
		}); err != nil {
			return "", err
		}
	}
	tree, err := git.Invoke(ctx, git.Root, gitrepo.Invocation{
		Arguments: []string{"write-tree"}, Environment: environment,
	})
	return strings.TrimSpace(string(tree)), err
}

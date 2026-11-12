// Package operations executes layer operations.
package operations

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

type entry struct{ path, mode, object string }

// GitCloneRequest identifies a Git source and its destination in the workspace.
type GitCloneRequest struct {
	URL               string
	Dir               string
	Ref               string
	Commit            string
	Depth             int
	PreCheckoutPatch  string
	PreCheckoutScript string
	DefinitionRoot    string
	LayerDirectory    string
	LayerID           string
	OperationIndex    int
}

// GitClone copies the tracked source tree into the destination relative to
// workspace, and imports its commit ancestry into the workspace object store.
// An empty Dir means the workspace root; absent Ref and Commit select HEAD.
// PreCheckoutPatch prepares the imported tree in a private index. The source
// commit remains the parent unless a following script returns another commit.
// Existing leaves are never replaced. The returned commit can be used as a
// parent of a composed commit; no ref is created and no commit is made here.
func GitClone(ctx context.Context, workspace string, req GitCloneRequest) (resultCommit string, resultErr error) {
	dir := req.Dir
	if req.URL == "" {
		return "", fmt.Errorf("git-clone URL is required")
	}
	if err := validDestination(dir); err != nil {
		return "", err
	}
	workspaceAbs, err := filepath.Abs(workspace)
	if err != nil {
		return "", fmt.Errorf("resolve workspace: %w", err)
	}
	workspaceRoot, err := git(ctx, workspace, "rev-parse", "--show-toplevel")
	if err != nil {
		return "", fmt.Errorf("workspace must be an initialized Git repository: %w", err)
	}
	actual, err := filepath.EvalSymlinks(workspaceAbs)
	if err != nil {
		return "", fmt.Errorf("resolve workspace: %w", err)
	}
	gitRoot, err := filepath.EvalSymlinks(strings.TrimSpace(string(workspaceRoot)))
	if err != nil || actual != gitRoot {
		return "", fmt.Errorf("workspace must be the Git repository root")
	}
	root, err := os.OpenRoot(workspace)
	if err != nil {
		return "", fmt.Errorf("open workspace: %w", err)
	}
	defer root.Close()
	temp, err := os.MkdirTemp("", "layerctl-import-")
	if err != nil {
		return "", fmt.Errorf("create clone staging directory: %w", err)
	}
	defer os.RemoveAll(temp)
	temp, err = filepath.EvalSymlinks(temp)
	if err != nil {
		return "", fmt.Errorf("resolve clone staging directory: %w", err)
	}
	source := filepath.Join(temp, "source")
	if req.Depth < 0 {
		return "", fmt.Errorf("git-clone depth must be positive when specified")
	}
	if strings.HasPrefix(req.Ref, "-") || strings.ContainsRune(req.Ref, 0) {
		return "", fmt.Errorf("invalid git-clone ref")
	}
	if req.Commit != "" && !regexp.MustCompile(`(?i)^([0-9a-f]{40}|[0-9a-f]{64})$`).MatchString(req.Commit) {
		return "", fmt.Errorf("git-clone commit must be a full hexadecimal object ID")
	}
	if err := os.Mkdir(source, 0700); err != nil {
		return "", err
	}
	initArgs := []string{"init", "-q"}
	if req.PreCheckoutScript != "" {
		initArgs = append(initArgs, "--bare")
	}
	if _, err := git(ctx, source, initArgs...); err != nil {
		return "", fmt.Errorf("initialize source repository: %w", err)
	}
	want := req.Ref
	if want == "" {
		want = req.Commit
	}
	if want == "" {
		want = "HEAD"
	}
	fetchArgs := []string{"-c", "protocol.file.allow=always", "fetch", "--no-tags"}
	if req.Depth > 0 {
		fetchArgs = append(fetchArgs, fmt.Sprintf("--depth=%d", req.Depth))
	}
	fetchArgs = append(fetchArgs, "--", req.URL, want)
	if _, err := git(ctx, source, fetchArgs...); err != nil {
		// Git diagnostics can include credentials embedded in the URL.
		return "", fmt.Errorf("fetch git-clone source or requested ref failed: %w", err)
	}
	result, err := git(ctx, source, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
	if err != nil {
		return "", fmt.Errorf("resolve fetched source commit: %w", err)
	}
	commit := strings.TrimSpace(string(result))
	if req.Commit != "" {
		result, err = git(ctx, source, "rev-parse", "--verify", "--end-of-options", req.Commit+"^{commit}")
		if err != nil {
			return "", fmt.Errorf("requested commit is unavailable in fetched ref; shallow depth may prevent verification")
		}
		commit = strings.TrimSpace(string(result))
		if !strings.EqualFold(commit, req.Commit) {
			return "", fmt.Errorf("requested commit is not the exact commit object")
		}
		if req.Ref != "" {
			if _, err := git(ctx, source, "merge-base", "--is-ancestor", commit, "FETCH_HEAD"); err != nil {
				return "", fmt.Errorf("requested commit is not reachable from ref, or shallow depth prevents verification")
			}
		}
	}
	treeish := commit
	if req.PreCheckoutPatch != "" || req.PreCheckoutScript != "" {
		index := filepath.Join(temp, "source.index")
		runIndex := func(args ...string) ([]byte, error) {
			cmd := exec.CommandContext(ctx, "git", append([]string{"-c", "core.ignorecase=false"}, args...)...)
			cmd.Dir = source
			cmd.Env = append(cleanGitRepositoryEnvironment(os.Environ()), "GIT_INDEX_FILE="+index, "GIT_TERMINAL_PROMPT=0")
			cmd.Stderr = io.Discard
			return cmd.Output()
		}
		if _, err := runIndex("read-tree", commit); err != nil {
			return "", fmt.Errorf("prepare source index: %w", err)
		}
		if req.PreCheckoutPatch != "" {
			if !filepath.IsAbs(req.PreCheckoutPatch) {
				return "", fmt.Errorf("pre-checkout patch path must be absolute")
			}
			info, err := os.Stat(req.PreCheckoutPatch)
			if err != nil || !info.Mode().IsRegular() {
				return "", fmt.Errorf("pre-checkout patch must be a readable regular file")
			}
			if _, err := runIndex("apply", "--cached", "--3way", "--", req.PreCheckoutPatch); err != nil {
				return "", fmt.Errorf("apply pre-checkout patch: %w", err)
			}
		}
		prepared, err := runIndex("write-tree")
		if err != nil {
			return "", fmt.Errorf("write pre-checkout tree: %w", err)
		}
		treeish = strings.TrimSpace(string(prepared))
		if req.PreCheckoutScript != "" {
			if !filepath.IsAbs(req.PreCheckoutScript) {
				return "", fmt.Errorf("pre-checkout script path must be absolute")
			}
			info, err := os.Stat(req.PreCheckoutScript)
			if err != nil || !info.Mode().IsRegular() || info.Mode()&0111 == 0 {
				return "", fmt.Errorf("pre-checkout script must be an executable regular file")
			}
			if req.LayerDirectory != "" {
				if err := ValidateScript(req.LayerDirectory, req.PreCheckoutScript); err != nil {
					return "", fmt.Errorf("validate pre-checkout script: %w", err)
				}
			}
			cmd := exec.CommandContext(ctx, req.PreCheckoutScript)
			cmd.Dir = source
			cmd.Env = append(cleanGitRepositoryEnvironment(os.Environ()),
				"GIT_DIR="+source, "GIT_INDEX_FILE="+index,
				"LAYERCTL_GIT_DIR="+source, "LAYERCTL_SOURCE_COMMIT="+commit,
				"LAYERCTL_SOURCE_TREE="+treeish, "LAYERCTL_WORKTREE_DIR="+workspaceAbs,
				"LAYERCTL_DEFINITION_DIR="+req.DefinitionRoot, "LAYERCTL_LAYER_DIR="+req.LayerDirectory,
				"LAYERCTL_LAYER_ID="+req.LayerID, "LAYERCTL_OPERATION_INDEX="+strconv.Itoa(req.OperationIndex))
			cmd.Stderr = os.Stderr
			var output boundedOutput
			cmd.Stdout = &output
			if err := cmd.Run(); err != nil {
				return "", fmt.Errorf("run pre-checkout script: %w", err)
			}
			value := strings.TrimSuffix(output.String(), "\n")
			if !regexp.MustCompile(`^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$`).MatchString(value) {
				return "", fmt.Errorf("pre-checkout script must print exactly one full commit or tree object ID")
			}
			kind, err := git(ctx, source, "cat-file", "-t", value)
			if err != nil {
				return "", fmt.Errorf("pre-checkout script returned an unavailable object")
			}
			switch strings.TrimSpace(string(kind)) {
			case "commit":
				commit = strings.ToLower(value)
				treeish = commit
			case "tree":
				treeish = strings.ToLower(value)
			default:
				return "", fmt.Errorf("pre-checkout script must return a commit or tree object")
			}
			if _, err := git(ctx, source, "update-ref", "refs/layerctl/selected", commit); err != nil {
				return "", fmt.Errorf("retain selected source commit: %w", err)
			}
		}
		// A temporary ref makes new blobs reachable during the later fetch.
		if _, err := git(ctx, source, "update-ref", "refs/layerctl/prepared", treeish); err != nil {
			return "", fmt.Errorf("retain pre-checkout tree: %w", err)
		}
	}
	tree, err := git(ctx, source, "ls-tree", "-rz", "--full-tree", treeish)
	if err != nil {
		return "", fmt.Errorf("list source tree: %w", err)
	}
	entries, err := parseTree(tree)
	if err != nil {
		return "", err
	}
	// Stage source bytes before touching the workspace, including symlinks and
	// executable bits. Git archive is unsuitable: export attributes change trees.
	staged := filepath.Join(temp, "files")
	if err := os.Mkdir(staged, 0700); err != nil {
		return "", err
	}
	if err := stageBlobs(ctx, source, staged, entries); err != nil {
		return "", err
	}

	// Fail before fetching or writing leaves if any existing path conflicts.
	for _, e := range entries {
		path := joined(dir, e.path)
		if err := checkPath(root, path); err != nil {
			return "", err
		}
	}
	if dir != "" {
		if err := checkDirectory(root, filepath.FromSlash(dir)); err != nil {
			return "", err
		}
	}
	if err := checkIndex(ctx, workspace, dir, entries); err != nil {
		return "", err
	}
	if err := checkShallowOverlap(ctx, workspace, source, commit); err != nil {
		return "", err
	}
	shallowPathBytes, err := git(ctx, workspace, "rev-parse", "--git-path", "shallow")
	if err != nil {
		return "", fmt.Errorf("resolve workspace shallow state: %w", err)
	}
	shallowPath := strings.TrimSpace(string(shallowPathBytes))
	if !filepath.IsAbs(shallowPath) {
		shallowPath = filepath.Join(workspace, shallowPath)
	}
	originalShallow, err := os.ReadFile(shallowPath)
	hadShallow := err == nil
	if err != nil && !os.IsNotExist(err) {
		return "", fmt.Errorf("read workspace shallow state: %w", err)
	}
	defer func() {
		if resultErr == nil {
			return
		}
		if err := restoreShallow(shallowPath, originalShallow, hadShallow); err != nil {
			resultErr = errors.Join(resultErr, fmt.Errorf("restore workspace shallow state: %w", err))
		}
	}()
	fetchObjects := []string{"-c", "protocol.file.allow=always", "fetch", "--update-shallow", "--no-tags", "--no-write-fetch-head", "--", source, commit}
	if req.PreCheckoutPatch != "" || req.PreCheckoutScript != "" {
		fetchObjects = append(fetchObjects, "refs/layerctl/prepared")
	}
	if req.PreCheckoutScript != "" {
		fetchObjects = append(fetchObjects, "refs/layerctl/selected")
	}
	if _, err := git(ctx, workspace, fetchObjects...); err != nil {
		return "", fmt.Errorf("import source commit objects: %w", err)
	}
	var createdFiles, createdDirs []string
	rollback := func() {
		for i := len(createdFiles) - 1; i >= 0; i-- {
			_ = root.Remove(createdFiles[i])
		}
		for i := len(createdDirs) - 1; i >= 0; i-- {
			_ = root.Remove(createdDirs[i])
		}
	}
	if dir != "" {
		if err := makeDirs(root, filepath.FromSlash(dir), &createdDirs); err != nil {
			rollback()
			return "", err
		}
	}
	for _, e := range entries {
		path := joined(dir, e.path)
		if err := makeDirs(root, filepath.Dir(path), &createdDirs); err != nil {
			rollback()
			return "", err
		}
		sourcePath := filepath.Join(staged, filepath.FromSlash(e.path))
		if e.mode == "120000" {
			target, err := os.Readlink(sourcePath)
			if err != nil {
				rollback()
				return "", err
			}
			if err := root.Symlink(target, path); err != nil {
				rollback()
				return "", fmt.Errorf("install symlink %q: %w", path, err)
			}
			createdFiles = append(createdFiles, path)
		} else {
			in, err := os.Open(sourcePath)
			if err != nil {
				rollback()
				return "", err
			}
			mode := fs.FileMode(0644)
			if e.mode == "100755" {
				mode = 0755
			}
			out, err := root.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
			if err != nil {
				in.Close()
				rollback()
				return "", fmt.Errorf("install file %q: %w", path, err)
			}
			createdFiles = append(createdFiles, path)
			if err := out.Chmod(mode); err != nil {
				out.Close()
				in.Close()
				rollback()
				return "", fmt.Errorf("set mode for %q: %w", path, err)
			}
			_, copyErr := io.Copy(out, in)
			closeErr := out.Close()
			in.Close()
			if copyErr != nil {
				rollback()
				return "", fmt.Errorf("write file %q: %w", path, copyErr)
			}
			if closeErr != nil {
				rollback()
				return "", fmt.Errorf("close file %q: %w", path, closeErr)
			}
		}
	}
	if err := stageIndex(ctx, workspace, temp, dir, entries); err != nil {
		rollback()
		return "", err
	}

	return commit, nil
}

// stageIndex changes only the imported paths. The temporary index preserves
// pre-existing staged changes and refreshes imported stat data so later Git
// three-way patches can apply. The real index is protected by Git's lock file.
func stageIndex(ctx context.Context, workspace, temp, dir string, entries []entry) error {
	if len(entries) == 0 {
		return nil
	}
	indexBytes, err := git(ctx, workspace, "rev-parse", "--git-path", "index")
	if err != nil {
		return fmt.Errorf("resolve workspace index: %w", err)
	}
	index := strings.TrimSpace(string(indexBytes))
	if !filepath.IsAbs(index) {
		index = filepath.Join(workspace, index)
	}
	lock, err := os.OpenFile(index+".lock", os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return fmt.Errorf("lock workspace index: %w", err)
	}
	defer os.Remove(index + ".lock")
	defer lock.Close()
	// Recheck while holding the index lock: another writer could have staged
	// a conflicting path after the earlier, pre-fetch check.
	if err := checkIndex(ctx, workspace, dir, entries); err != nil {
		return err
	}
	original, err := os.ReadFile(index)
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("read workspace index: %w", err)
	}
	tempIndex := filepath.Join(temp, "import.index")
	if err == nil {
		if err := os.WriteFile(tempIndex, original, 0600); err != nil {
			return fmt.Errorf("copy workspace index: %w", err)
		}
	} else {
		cmd := exec.CommandContext(ctx, "git", "read-tree", "--empty")
		cmd.Dir = workspace
		cmd.Env = append(cleanGitRepositoryEnvironment(os.Environ()), "GIT_INDEX_FILE="+tempIndex)
		cmd.Stderr = io.Discard
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("initialize temporary index: %w", err)
		}
	}
	var indexInfo, paths bytes.Buffer
	for _, e := range entries {
		path := filepath.ToSlash(joined(dir, e.path))
		fmt.Fprintf(&indexInfo, "%s %s\t%s%c", e.mode, e.object, path, 0)
		paths.WriteString(path)
		paths.WriteByte(0)
	}
	update := exec.CommandContext(ctx, "git", "update-index", "-z", "--index-info")
	update.Dir = workspace
	update.Env = append(cleanGitRepositoryEnvironment(os.Environ()), "GIT_INDEX_FILE="+tempIndex)
	update.Stdin = &indexInfo
	update.Stderr = io.Discard
	if err := update.Run(); err != nil {
		return fmt.Errorf("stage imported files: %w", err)
	}
	refresh := exec.CommandContext(ctx, "git", "update-index", "--refresh", "-z", "--stdin")
	refresh.Dir = workspace
	refresh.Env = append(cleanGitRepositoryEnvironment(os.Environ()), "GIT_INDEX_FILE="+tempIndex)
	refresh.Stdin = &paths
	refresh.Stderr = io.Discard
	if err := refresh.Run(); err != nil {
		return fmt.Errorf("refresh imported files in index: %w", err)
	}
	f, err := os.Open(tempIndex)
	if err != nil {
		return fmt.Errorf("read prepared index: %w", err)
	}
	_, copyErr := io.Copy(lock, f)
	closeErr := f.Close()
	if copyErr != nil {
		return fmt.Errorf("write prepared index: %w", copyErr)
	}
	if closeErr != nil {
		return closeErr
	}
	if err := lock.Close(); err != nil {
		return fmt.Errorf("close index lock: %w", err)
	}
	if err := os.Rename(index+".lock", index); err != nil {
		return fmt.Errorf("install workspace index: %w", err)
	}
	return nil
}

// checkIndex prevents replacing staged content even if its working-tree file
// was deleted; successful imports stage exactly the new tracked source paths.
func checkIndex(ctx context.Context, workspace, dir string, entries []entry) error {
	index, err := git(ctx, workspace, "ls-files", "--stage", "-z")
	if err != nil {
		return fmt.Errorf("inspect workspace index: %w", err)
	}
	var paths []string
	for _, record := range bytes.Split(index, []byte{0}) {
		if len(record) == 0 {
			continue
		}
		_, path, ok := bytes.Cut(record, []byte{'\t'})
		if !ok {
			return fmt.Errorf("invalid workspace index record")
		}
		paths = append(paths, string(path))
	}
	for _, e := range entries {
		path := filepath.ToSlash(joined(dir, e.path))
		for _, existing := range paths {
			if path == existing || strings.HasPrefix(path, existing+"/") || strings.HasPrefix(existing, path+"/") {
				return fmt.Errorf("git-clone destination conflicts with workspace index: %q", path)
			}
		}
	}
	return nil
}

// stageBlobs streams binary Git objects through one batch process. This keeps
// memory bounded and avoids spawning one Git process for every tracked file.
func stageBlobs(ctx context.Context, source, staged string, entries []entry) error {
	if len(entries) == 0 {
		return nil
	}
	root, err := os.OpenRoot(staged)
	if err != nil {
		return fmt.Errorf("open source staging directory: %w", err)
	}
	defer root.Close()
	var createdDirs []string
	cmd := exec.CommandContext(ctx, "git", "cat-file", "--batch")
	cmd.Dir = source
	cmd.Env = cleanGitRepositoryEnvironment(os.Environ())
	cmd.Stderr = io.Discard
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("start Git blob reader: %w", err)
	}
	complete := false
	defer func() {
		if !complete {
			stdin.Close()
			_ = cmd.Process.Kill()
			_ = cmd.Wait()
		}
	}()
	reader := bufio.NewReader(stdout)
	for _, e := range entries {
		if _, err := io.WriteString(stdin, e.object+"\n"); err != nil {
			return fmt.Errorf("request source blob %q: %w", e.path, err)
		}
		header, err := reader.ReadString('\n')
		if err != nil {
			return fmt.Errorf("read source blob header %q: %w", e.path, err)
		}
		parts := strings.Fields(header)
		if len(parts) != 3 || parts[0] != e.object || parts[1] != "blob" {
			return fmt.Errorf("invalid source blob response for %q", e.path)
		}
		size, err := strconv.ParseInt(parts[2], 10, 64)
		if err != nil || size < 0 {
			return fmt.Errorf("invalid source blob size for %q", e.path)
		}
		path := filepath.FromSlash(e.path)
		if err := makeDirs(root, filepath.Dir(path), &createdDirs); err != nil {
			return err
		}
		if e.mode == "120000" {
			// A symlink target cannot exceed the OS path limit, and must not become a
			// huge in-memory allocation when given a malformed source repository.
			if size > 1024*1024 {
				return fmt.Errorf("source symlink target too large: %q", e.path)
			}
			target, err := io.ReadAll(io.LimitReader(reader, size))
			if err != nil {
				return err
			}
			if int64(len(target)) != size {
				return fmt.Errorf("short source symlink target: %q", e.path)
			}
			if err := root.Symlink(string(target), path); err != nil {
				return fmt.Errorf("stage symlink %q: %w", e.path, err)
			}
		} else {
			mode := fs.FileMode(0644)
			if e.mode == "100755" {
				mode = 0755
			}
			f, err := root.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
			if err != nil {
				return fmt.Errorf("stage file %q: %w", e.path, err)
			}
			_, copyErr := io.CopyN(f, reader, size)
			closeErr := f.Close()
			if copyErr != nil {
				return fmt.Errorf("read source blob %q: %w", e.path, copyErr)
			}
			if closeErr != nil {
				return fmt.Errorf("close staged file %q: %w", e.path, closeErr)
			}
		}
		delimiter, err := reader.ReadByte()
		if err != nil || delimiter != '\n' {
			return fmt.Errorf("invalid source blob delimiter for %q", e.path)
		}
	}
	if err := stdin.Close(); err != nil {
		return err
	}
	err = cmd.Wait()
	complete = true
	if err != nil {
		return fmt.Errorf("finish Git blob reader: %w", err)
	}
	return nil
}

func git(ctx context.Context, dir string, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, "git", args...)
	cmd.Dir = dir
	cmd.Env = append(cleanGitRepositoryEnvironment(os.Environ()), "GIT_TERMINAL_PROMPT=0")
	// Suppress stderr: clone/fetch errors can expose URL userinfo or tokens.
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = io.Discard
	if err := cmd.Run(); err != nil {
		return nil, err
	}
	return out.Bytes(), nil
}

// Remove repository-selection variables from subprocesses while preserving
// transport settings such as GIT_SSH_COMMAND for authenticated fetches.
func cleanGitRepositoryEnvironment(env []string) []string {
	blocked := map[string]bool{
		"GIT_DIR": true, "GIT_WORK_TREE": true, "GIT_INDEX_FILE": true,
		"GIT_COMMON_DIR": true, "GIT_OBJECT_DIRECTORY": true,
		"GIT_ALTERNATE_OBJECT_DIRECTORIES": true, "GIT_SHALLOW_FILE": true,
		"GIT_NAMESPACE": true, "GIT_PREFIX": true,
	}
	filtered := make([]string, 0, len(env))
	for _, item := range env {
		key, _, _ := strings.Cut(item, "=")
		if !blocked[key] {
			filtered = append(filtered, item)
		}
	}
	return filtered
}

type boundedOutput struct{ bytes.Buffer }

func (b *boundedOutput) Write(p []byte) (int, error) {
	if b.Len()+len(p) > 65 {
		return 0, fmt.Errorf("pre-checkout script output exceeds one object ID")
	}
	return b.Buffer.Write(p)
}
func validDestination(path string) error {
	if path == "" {
		return nil
	}
	if !fs.ValidPath(path) || path == "." || !filepath.IsLocal(path) || strings.Contains(path, `\`) {
		return fmt.Errorf("invalid git-clone destination %q", path)
	}
	for _, p := range strings.Split(path, "/") {
		if strings.EqualFold(p, ".git") {
			return fmt.Errorf("git-clone destination addresses Git metadata")
		}
	}
	return nil
}
func parseTree(tree []byte) ([]entry, error) {
	var entries []entry
	for _, rec := range bytes.Split(tree, []byte{0}) {
		if len(rec) == 0 {
			continue
		}
		header, pathBytes, ok := bytes.Cut(rec, []byte{'\t'})
		fields := strings.Fields(string(header))
		path := string(pathBytes)
		if !ok || len(fields) != 3 || validDestination(path) != nil {
			return nil, fmt.Errorf("invalid source tree entry %q", path)
		}
		mode, kind := fields[0], fields[1]
		if mode == "160000" || kind == "commit" {
			return nil, fmt.Errorf("git-clone source contains submodule %q", path)
		}
		if kind != "blob" || (mode != "100644" && mode != "100755" && mode != "120000") {
			return nil, fmt.Errorf("unsupported source tree entry %q", path)
		}
		entries = append(entries, entry{path: path, mode: mode, object: fields[2]})
	}
	return entries, nil
}
func joined(dir, path string) string {
	if dir == "" {
		return filepath.FromSlash(path)
	}
	return filepath.Join(filepath.FromSlash(dir), filepath.FromSlash(path))
}
func checkPath(root *os.Root, path string) error {
	if err := checkDirectory(root, filepath.Dir(path)); err != nil {
		return err
	}
	_, err := root.Lstat(path)
	if err == nil {
		return fmt.Errorf("git-clone destination already exists: %q", path)
	}
	if !os.IsNotExist(err) {
		return fmt.Errorf("inspect destination %q: %w", path, err)
	}
	return nil
}
func checkDirectory(root *os.Root, path string) error {
	if path == "." || path == "" {
		return nil
	}
	current := ""
	for _, part := range strings.Split(path, string(filepath.Separator)) {
		current = filepath.Join(current, part)
		info, err := root.Lstat(current)
		if os.IsNotExist(err) {
			return nil
		}
		if err != nil {
			return fmt.Errorf("inspect destination %q: %w", current, err)
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("destination parent is not a directory: %q", current)
		}
	}
	return nil
}
func makeDirs(root *os.Root, path string, created *[]string) error {
	if path == "." || path == "" {
		return nil
	}
	current := ""
	for _, part := range strings.Split(path, string(filepath.Separator)) {
		current = filepath.Join(current, part)
		info, err := root.Lstat(current)
		if os.IsNotExist(err) {
			if err := root.Mkdir(current, 0755); err != nil {
				return fmt.Errorf("create directory %q: %w", current, err)
			}
			*created = append(*created, current)
			continue
		}
		if err != nil {
			return fmt.Errorf("inspect directory %q: %w", current, err)
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("destination parent is not a directory: %q", current)
		}
	}
	return nil
}

// Git shallow boundaries apply to the whole object database, not an individual
// source. Overlapping shallow imports could silently truncate another history.
func checkShallowOverlap(ctx context.Context, workspace, source, commit string) error {
	incoming, err := git(ctx, source, "rev-parse", "--is-shallow-repository")
	if err != nil {
		return fmt.Errorf("inspect source shallow state: %w", err)
	}
	existing, err := git(ctx, workspace, "rev-parse", "--is-shallow-repository")
	if err != nil {
		return fmt.Errorf("inspect workspace Git repository: %w", err)
	}
	if strings.TrimSpace(string(incoming)) != "true" && strings.TrimSpace(string(existing)) != "true" {
		return nil
	}
	ids, err := git(ctx, source, "rev-list", commit)
	if err != nil {
		return fmt.Errorf("inspect source ancestry: %w", err)
	}
	cmd := exec.CommandContext(ctx, "git", "cat-file", "--batch-check=%(objectname) %(objecttype)")
	cmd.Dir = workspace
	cmd.Env = cleanGitRepositoryEnvironment(os.Environ())
	cmd.Stdin = bytes.NewReader(ids)
	cmd.Stderr = io.Discard
	output, err := cmd.Output()
	if err != nil {
		return fmt.Errorf("inspect workspace ancestry: %w", err)
	}
	for _, line := range strings.Split(strings.TrimSpace(string(output)), "\n") {
		if strings.HasSuffix(line, " commit") {
			return fmt.Errorf("cannot import overlapping source histories while either repository is shallow")
		}
	}
	return nil
}

// Import runs serially in an isolated Git store. Restore its preexisting
// shallow boundary if fetch or installation fails, without touching its refs.
func restoreShallow(path string, content []byte, hadFile bool) error {
	if !hadFile {
		err := os.Remove(path)
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".layerctl-shallow-")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if err := tmp.Chmod(0644); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(content); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}

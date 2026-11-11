// Package commitauthors formats the co-author metadata of a layer commit.
package commitauthors

import (
	"bytes"
	"fmt"
	"regexp"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
)

var trailerLine = regexp.MustCompile(`^[A-Za-z0-9-]+:[\t ]*.*$`)

// Message returns the exact raw message when no coauthors are configured.
// Otherwise it appends missing standard Git trailers, preserving an existing
// trailer block and omitting duplicate coauthor lines.
func Message(unit definition.Unit, raw []byte) ([]byte, error) {
	if len(unit.CoAuthors) == 0 {
		return raw, nil
	}
	if len(raw) == 0 {
		return nil, fmt.Errorf("commit message must not be empty")
	}
	for _, author := range unit.CoAuthors {
		if err := definition.ValidateCoAuthor(author); err != nil {
			return nil, err
		}
	}
	// A trailer block is a contiguous block of trailer and continuation lines at
	// the end, separated from the body by a blank line.
	trimmed := bytes.TrimRight(raw, "\n")
	lines := bytes.Split(trimmed, []byte("\n"))
	first := len(lines)
	for first > 0 {
		line := lines[first-1]
		if trailerLine.Match(line) || len(line) > 0 && (line[0] == ' ' || line[0] == '\t') {
			first--
			continue
		}
		break
	}
	hasTrailer := first < len(lines) && first > 0 && len(bytes.TrimSpace(lines[first-1])) == 0
	existing := map[string]bool{}
	if hasTrailer {
		for _, line := range lines[first:] {
			existing[string(bytes.TrimSuffix(line, []byte("\r")))] = true
		}
	}
	var additions []string
	for _, author := range unit.CoAuthors {
		trailer := "Co-authored-by: " + author
		if !existing[trailer] {
			additions = append(additions, trailer)
			existing[trailer] = true
		}
	}
	if len(additions) == 0 {
		return raw, nil
	}
	result := append([]byte(nil), raw...)
	if hasTrailer {
		result = append(result[:len(bytes.TrimRight(result, "\n"))], '\n')
	} else {
		n := len(raw) - len(bytes.TrimRight(raw, "\n"))
		if n == 0 {
			result = append(result, '\n', '\n')
		} else if n == 1 {
			result = append(result, '\n')
		}
	}
	for _, line := range additions {
		result = append(result, line...)
		result = append(result, '\n')
	}
	return result, nil
}

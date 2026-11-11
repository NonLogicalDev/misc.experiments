package commitauthors_test

import (
	"bytes"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/commitauthors"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
)

func TestNoCoAuthorsPreservesExactBytes(t *testing.T) {
	for _, raw := range [][]byte{[]byte("summary"), []byte("summary\n\n\n"), {0xff, 0x00}} {
		got, err := commitauthors.Message(definition.Unit{}, raw)
		if err != nil || !bytes.Equal(got, raw) {
			t.Fatalf("got %q, %v; want %q", got, err, raw)
		}
	}
}
func TestAddsCoAuthorsAndPreservesExistingTrailers(t *testing.T) {
	cases := []struct {
		name, raw, want string
		authors         []string
	}{
		{"no newline", "Summary", "Summary\n\nCo-authored-by: Alice <alice@example.com>\n", []string{"Alice <alice@example.com>"}},
		{"body with newline", "Summary\n\nBody\n", "Summary\n\nBody\n\nCo-authored-by: Alice <alice@example.com>\n", []string{"Alice <alice@example.com>"}},
		{"existing block", "Summary\n\nSigned-off-by: Bob <bob@example.com>\n", "Summary\n\nSigned-off-by: Bob <bob@example.com>\nCo-authored-by: Alice <alice@example.com>\n", []string{"Alice <alice@example.com>"}},
		{"deduplicate", "Summary\n\nCo-authored-by: Alice <alice@example.com>\n", "Summary\n\nCo-authored-by: Alice <alice@example.com>\nCo-authored-by: Bob <bob@example.com>\n", []string{"Alice <alice@example.com>", "Bob <bob@example.com>", "Bob <bob@example.com>"}},
		{"no changes", "Summary\n\nCo-authored-by: Alice <alice@example.com>\n\n", "Summary\n\nCo-authored-by: Alice <alice@example.com>\n\n", []string{"Alice <alice@example.com>"}},
		{"CRLF duplicate", "Summary\r\n\r\nCo-authored-by: Alice <alice@example.com>\r\n", "Summary\r\n\r\nCo-authored-by: Alice <alice@example.com>\r\n", []string{"Alice <alice@example.com>"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := commitauthors.Message(definition.Unit{CoAuthors: tc.authors}, []byte(tc.raw))
			if err != nil || string(got) != tc.want {
				t.Fatalf("got %q, %v; want %q", got, err, tc.want)
			}
		})
	}
}
func TestRejectsInvalidCoAuthor(t *testing.T) {
	for _, author := range []string{"", "Alice", "Alice <bad>", " <a@example.com>", "Alice <a@example.com>\nInjected", "Alice <a@example.com>\x00", "Alice <a@example.com> <b@example.com>", "Alice <a b@example.com>", "Alice <@example.com>", "Alice <a@>"} {
		if _, err := commitauthors.Message(definition.Unit{CoAuthors: []string{author}}, []byte("summary\n")); err == nil {
			t.Errorf("accepted %q", author)
		}
	}
}

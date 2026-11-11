package definition

import (
	"fmt"
	"net/mail"
	"strings"
	"unicode"
	"unicode/utf8"
)

// ValidateCoAuthor accepts exactly a display name followed by one email in
// angle brackets. It excludes control characters and ambiguous delimiters so
// each configured identity can safely occupy one Git trailer line.
func ValidateCoAuthor(value string) error {
	invalid := func() error { return fmt.Errorf("invalid co-author; expected Name <email>") }
	if !utf8.ValidString(value) || strings.TrimSpace(value) != value || !strings.HasSuffix(value, ">") {
		return invalid()
	}
	for _, c := range value {
		if unicode.IsControl(c) {
			return invalid()
		}
	}
	name, email, ok := strings.Cut(value, " <")
	if !ok || name == "" || strings.TrimSpace(name) != name || strings.ContainsAny(name, "<>") {
		return invalid()
	}
	email = strings.TrimSuffix(email, ">")
	if strings.ContainsAny(email, "<>") || strings.Count(email, "@") != 1 {
		return invalid()
	}
	local, domain, _ := strings.Cut(email, "@")
	if local == "" || domain == "" || strings.IndexFunc(email, unicode.IsSpace) >= 0 {
		return invalid()
	}
	parsed, err := mail.ParseAddress(email)
	if err != nil || parsed.Name != "" || parsed.Address != email {
		return invalid()
	}
	return nil
}

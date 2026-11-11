package layer

import (
	"encoding/json"
	"strings"
)

// multilineMessage keeps the exact message, including whether it ends in a
// newline. TOML trims the newline immediately after the opening delimiter.
func multilineMessage(message string) string {
	quoted, _ := json.Marshal(message)
	var out strings.Builder
	out.WriteString("\"\"\"\n")
	for i := 1; i < len(quoted)-1; i++ {
		if quoted[i] == '\\' {
			i++
			if quoted[i] == 'n' {
				out.WriteByte('\n')
			} else {
				out.WriteByte('\\')
				out.WriteByte(quoted[i])
			}
		} else if quoted[i] == 0x7f {
			out.WriteString(`\u007f`)
		} else {
			out.WriteByte(quoted[i])
		}
	}
	out.WriteString("\"\"\"")
	return out.String()
}

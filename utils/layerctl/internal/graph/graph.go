// Package graph renders a layer dependency graph without external tools.
package graph

import (
	"fmt"
	"io"
	"strconv"
	"strings"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
)

// Write renders dependency edges from prerequisite to dependent. When a layer
// omits depends-on, its prerequisite is the preceding enabled layer. An
// explicitly empty list declares no prerequisites. No output is written for an
// unsupported format or an invalid graph.
func Write(w io.Writer, layers []definition.Unit, format string) error {
	if format != "dot" && format != "mermaid" {
		return fmt.Errorf("unsupported graph format %q (use dot or mermaid)", format)
	}
	ids := make(map[string]int, len(layers))
	for i, layer := range layers {
		if layer.ID == "" {
			return fmt.Errorf("layer ID must not be empty")
		}
		if _, ok := ids[layer.ID]; ok {
			return fmt.Errorf("duplicate layer ID %q", layer.ID)
		}
		ids[layer.ID] = i
	}
	for _, layer := range layers {
		for _, dep := range layer.DependsOn {
			if _, ok := ids[dep]; !ok {
				return fmt.Errorf("layer %q depends on unknown layer %q", layer.ID, dep)
			}
		}
	}
	dependencies := make([][]int, len(layers))
	previousEnabled := -1
	for i, layer := range layers {
		if layer.DependsOn == nil {
			if previousEnabled >= 0 {
				dependencies[i] = append(dependencies[i], previousEnabled)
			}
		} else {
			for _, dep := range layer.DependsOn {
				dependencies[i] = append(dependencies[i], ids[dep])
			}
		}
		if !layer.Disabled {
			previousEnabled = i
		}
	}
	var b strings.Builder
	switch format {
	case "dot":
		b.WriteString("digraph layers {\n  rankdir=LR;\n")
		for i, layer := range layers {
			label := layer.ID
			if layer.Disabled {
				label += " (disabled)"
			}
			fmt.Fprintf(&b, "  n%d [label=%s", i, strconv.Quote(label))
			if layer.Disabled {
				b.WriteString(", style=\"dashed,filled\", fillcolor=\"#f2f2f2\", fontcolor=\"#666666\"")
			}
			b.WriteString("];\n")
		}
		for i, deps := range dependencies {
			for _, dep := range deps {
				fmt.Fprintf(&b, "  n%d -> n%d;\n", dep, i)
			}
		}
		b.WriteString("}\n")
	case "mermaid":
		b.WriteString("flowchart LR\n")
		for i, layer := range layers {
			label := layer.ID
			if layer.Disabled {
				label += " (disabled)"
			}
			fmt.Fprintf(&b, "  n%d[\"%s\"]\n", i, mermaidLabel(label))
		}
		for i, deps := range dependencies {
			for _, dep := range deps {
				fmt.Fprintf(&b, "  n%d --> n%d\n", dep, i)
			}
		}
		for i, layer := range layers {
			if layer.Disabled {
				fmt.Fprintf(&b, "  class n%d disabled\n", i)
			}
		}
		if anyDisabled(layers) {
			b.WriteString("  classDef disabled fill:#f2f2f2,stroke:#999,color:#666,stroke-dasharray: 5 5\n")
		}
	}
	n, err := io.WriteString(w, b.String())
	if err != nil {
		return err
	}
	if n != b.Len() {
		return io.ErrShortWrite
	}
	return nil
}

func anyDisabled(layers []definition.Unit) bool {
	for _, layer := range layers {
		if layer.Disabled {
			return true
		}
	}
	return false
}

// Mermaid accepts character references such as #34; inside quoted labels.
// Encode syntax-significant characters so the label cannot create nodes or edges.
func mermaidLabel(s string) string {
	var b strings.Builder
	for _, r := range s {
		switch {
		case r < ' ' || r == 0x7f || strings.ContainsRune("#&<>\"[](){}|`", r):
			fmt.Fprintf(&b, "#%d;", r)
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

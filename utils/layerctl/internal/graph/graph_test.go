package graph_test

import (
	"bytes"
	"errors"
	"io"
	"strings"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/graph"
)

func TestWriteGraphShowsDependenciesAndDisabledLayers(t *testing.T) {
	layers := []definition.Unit{
		{ID: "0000-base"},
		{ID: "0001-optional", Disabled: true},
		{ID: "0002-feature", DependsOn: []string{"0000-base"}},
	}
	cases := []struct{ format, want string }{
		{"dot", `digraph layers {
  rankdir=LR;
  n0 [label="0000-base"];
  n1 [label="0001-optional (disabled)", style="dashed,filled", fillcolor="#f2f2f2", fontcolor="#666666"];
  n2 [label="0002-feature"];
  n0 -> n1;
  n0 -> n2;
}
`},
		{"mermaid", `flowchart LR
  n0["0000-base"]
  n1["0001-optional #40;disabled#41;"]
  n2["0002-feature"]
  n0 --> n1
  n0 --> n2
  class n1 disabled
  classDef disabled fill:#f2f2f2,stroke:#999,color:#666,stroke-dasharray: 5 5
`},
	}
	for _, tc := range cases {
		t.Run(tc.format, func(t *testing.T) {
			for i := 0; i < 2; i++ {
				var b bytes.Buffer
				if err := graph.Write(&b, layers, tc.format); err != nil {
					t.Fatal(err)
				}
				if b.String() != tc.want {
					t.Fatalf("graph = %q, want %q", b.String(), tc.want)
				}
			}
		})
	}
}

func TestWriteGraphDefaultsAndExplicitDependencies(t *testing.T) {
	layers := []definition.Unit{
		{ID: "base"},
		{ID: "disabled", Disabled: true},
		{ID: "default"},
		{ID: "independent", DependsOn: []string{}},
		{ID: "branch", DependsOn: []string{"base"}},
		{ID: "join", DependsOn: []string{"default", "branch"}},
	}
	for _, format := range []string{"dot", "mermaid"} {
		t.Run(format, func(t *testing.T) {
			var b bytes.Buffer
			if err := graph.Write(&b, layers, format); err != nil {
				t.Fatal(err)
			}
			arrow := " -> "
			if format == "mermaid" {
				arrow = " --> "
			}
			for _, edge := range []string{"n0" + arrow + "n1", "n0" + arrow + "n2", "n0" + arrow + "n4", "n2" + arrow + "n5", "n4" + arrow + "n5"} {
				if !strings.Contains(b.String(), edge) {
					t.Errorf("missing dependency %q in %s", edge, b.String())
				}
			}
			for _, edge := range []string{"n1" + arrow + "n2", "n2" + arrow + "n3", "n3" + arrow + "n4"} {
				if strings.Contains(b.String(), edge) {
					t.Errorf("unexpected dependency %q in %s", edge, b.String())
				}
			}
		})
	}
}

func TestWriteEscapesLabelsAndUsesSafeNodeIDs(t *testing.T) {
	layers := []definition.Unit{{ID: "a\"]\nmalicious --> target"}, {ID: "normal", DependsOn: []string{"a\"]\nmalicious --> target"}}}
	var dot, mermaid bytes.Buffer
	if err := graph.Write(&dot, layers, "dot"); err != nil {
		t.Fatal(err)
	}
	if err := graph.Write(&mermaid, layers, "mermaid"); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(dot.String(), `label="a\"]\nmalicious --> target"`) {
		t.Fatalf("DOT label not escaped: %q", dot.String())
	}
	if strings.Contains(mermaid.String(), "\nmalicious") || !strings.Contains(mermaid.String(), "a#34;#93;#10;malicious --#62; target") {
		t.Fatalf("Mermaid label not escaped: %q", mermaid.String())
	}
	if !strings.Contains(dot.String(), "n0 -> n1;") || !strings.Contains(mermaid.String(), "n0 --> n1") {
		t.Fatal("expected dependency edge")
	}
}
func TestWriteRejectsInvalidGraphsWithoutOutput(t *testing.T) {
	cases := []struct {
		format string
		units  []definition.Unit
	}{
		{"svg", nil},
		{"dot", []definition.Unit{{ID: "same"}, {ID: "same"}}},
		{"dot", []definition.Unit{{ID: "a", DependsOn: []string{"missing"}}}},
		{"mermaid", []definition.Unit{{ID: ""}}},
	}
	for _, tc := range cases {
		var b bytes.Buffer
		if err := graph.Write(&b, tc.units, tc.format); err == nil {
			t.Fatalf("accepted invalid graph: %#v", tc)
		}
		if b.Len() != 0 {
			t.Fatalf("wrote partial graph: %q", b.String())
		}
	}
}

type failWriter struct{}

func (failWriter) Write([]byte) (int, error) { return 0, errors.New("write failed") }

type shortWriter struct{}

func (shortWriter) Write(b []byte) (int, error) { return len(b) / 2, nil }
func TestWritePropagatesWriterFailures(t *testing.T) {
	if err := graph.Write(failWriter{}, nil, "dot"); err == nil || !strings.Contains(err.Error(), "write failed") {
		t.Fatalf("write error = %v", err)
	}
	if err := graph.Write(shortWriter{}, nil, "dot"); !errors.Is(err, io.ErrShortWrite) {
		t.Fatalf("short write error = %v", err)
	}
}

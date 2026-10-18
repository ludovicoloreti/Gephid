package main

import (
	"os"
	"path/filepath"
	"testing"
)

func runtimeFile(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("#!/bin/sh\nexit 0\n"), 0755); err != nil {
		t.Fatal(err)
	}
}

func TestResolveRuntimeUsesBundledPythonAfterRelocation(t *testing.T) {
	root := filepath.Join(t.TempDir(), "Another Folder", "Gephid.app")
	python := filepath.Join(root, "Contents", "Resources", "python", "bin", "python3")
	script := filepath.Join(root, "Contents", "Resources", "diffuchat.py")
	runtimeFile(t, python)
	runtimeFile(t, script)
	t.Setenv("GEPHID_PYTHON", "/does/not/exist")
	gotPython, gotScript, err := resolveRuntime(filepath.Join(root, "Contents", "MacOS", "Gephid"), t.TempDir())
	if err != nil || gotPython != python || gotScript != script {
		t.Fatalf("%s %s %v", gotPython, gotScript, err)
	}
}

func TestResolveRuntimeFindsCheckoutFromWorkingDirectory(t *testing.T) {
	root := filepath.Join(t.TempDir(), "Any checkout name")
	python := filepath.Join(root, ".venv", "bin", "python3")
	script := filepath.Join(root, "src", "backend", "diffuchat.py")
	runtimeFile(t, python)
	runtimeFile(t, script)
	t.Setenv("GEPHID_PYTHON", "")
	gotPython, gotScript, err := resolveRuntime(filepath.Join(t.TempDir(), "go-build", "launcher"), filepath.Join(root, "src", "launcher"))
	if err != nil || gotPython != python || gotScript != script {
		t.Fatalf("%s %s %v", gotPython, gotScript, err)
	}
}

func TestResolveRuntimeSupportsExplicitInterpreter(t *testing.T) {
	root := t.TempDir()
	script := filepath.Join(root, "src", "backend", "diffuchat.py")
	python := filepath.Join(t.TempDir(), "custom python")
	runtimeFile(t, script)
	runtimeFile(t, python)
	t.Setenv("GEPHID_PYTHON", python)
	gotPython, gotScript, err := resolveRuntime(filepath.Join(root, "bin", "Gephid"), t.TempDir())
	if err != nil || gotPython != python || gotScript != script {
		t.Fatalf("%s %s %v", gotPython, gotScript, err)
	}
}

func TestResolveRuntimeReportsMissingCheckout(t *testing.T) {
	_, _, err := resolveRuntime(filepath.Join(t.TempDir(), "Gephid"), t.TempDir())
	if err == nil {
		t.Fatal("missing backend accepted")
	}
}

func TestBackendPathPreservesCustomTools(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "my tools")
	t.Setenv("PATH", dir+string(os.PathListSeparator)+"/usr/bin")
	got := filepath.SplitList(backendPath())
	if len(got) == 0 || got[0] != dir {
		t.Fatalf("custom tool directory lost: %v", got)
	}
	seen := map[string]bool{}
	for _, path := range got {
		if path == "" || seen[path] {
			t.Fatalf("empty or duplicate PATH entry: %v", got)
		}
		seen[path] = true
	}
	if !seen["/usr/local/bin"] || !seen["/usr/bin"] {
		t.Fatalf("standard tools missing: %v", got)
	}
}

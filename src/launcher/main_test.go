package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestInitPortMatchesBackend(t *testing.T) {
	for _, tt := range []struct {
		name, config, want string
	}{
		{"default", `{}`, "8890"},
		{"custom", `{"port":9000}`, "9000"},
		{"numeric string", `{"port":" 9001 "}`, "9001"},
		{"low", `{"port":80}`, "1024"},
		{"zero", `{"port":0}`, "1024"},
		{"negative", `{"port":-1}`, "1024"},
		{"high", `{"port":99999}`, "65535"},
		{"fraction", `{"port":9002.9}`, "9002"},
		{"null", `{"port":null}`, "8890"},
		{"invalid string", `{"port":"wrong"}`, "8890"},
		{"invalid json", `{broken`, "8890"},
	} {
		t.Run(tt.name, func(t *testing.T) {
			home := t.TempDir()
			dir := filepath.Join(home, ".config", "diffuchat")
			if err := os.MkdirAll(dir, 0755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(dir, "config.json"), []byte(tt.config), 0600); err != nil {
				t.Fatal(err)
			}
			initPort(home)
			if backendAddr != "127.0.0.1:"+tt.want || healthURL != "http://localhost:"+tt.want+"/api/health" || backendURL != "http://localhost:"+tt.want+"/" {
				t.Fatalf("inconsistent port: %s %s %s; want %s", backendAddr, healthURL, backendURL, tt.want)
			}
		})
	}
}

func TestBackendDoesNotModifySignedPythonResources(t *testing.T) {
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Fatal(err)
	}
	home := t.TempDir()
	script := filepath.Join(home, "backend.py")
	if err := os.WriteFile(filepath.Join(home, "helper.py"), []byte("VALUE = 42\n"), 0600); err != nil {
		t.Fatal(err)
	}
	code := "import sys, helper, subprocess\nassert sys.dont_write_bytecode\nsubprocess.run([sys.executable, '-c', 'import sys; assert sys.dont_write_bytecode'], check=True)\n"
	if err := os.WriteFile(script, []byte(code), 0600); err != nil {
		t.Fatal(err)
	}
	_, died, err := startBackend(python, script, home)
	if err != nil {
		t.Fatal(err)
	}
	if err := <-died; err != nil {
		t.Fatalf("backend or its child writes bytecode: %v", err)
	}
	if _, err := os.Stat(filepath.Join(home, "__pycache__")); !os.IsNotExist(err) {
		t.Fatalf("Python created a bytecode cache inside the signed resources: %v", err)
	}
}

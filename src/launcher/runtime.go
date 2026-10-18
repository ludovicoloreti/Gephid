package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

func executableFile(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir() && info.Mode()&0111 != 0
}

// Il bundle si risolve rispetto al binario; lo sviluppo rispetto al checkout,
// anche se rinominato o aperto da una sottocartella.
func resolveRuntime(executable, workingDir string) (string, string, error) {
	resources := filepath.Clean(filepath.Join(filepath.Dir(executable), "..", "Resources"))
	script := filepath.Join(resources, "diffuchat.py")
	python := filepath.Join(resources, "python", "bin", "python3")
	if info, err := os.Stat(script); err == nil && !info.IsDir() {
		if !executableFile(python) {
			return "", "", fmt.Errorf("runtime Python mancante: %s; ricostruisci Gephid con build.sh", python)
		}
		return python, script, nil
	}
	for _, start := range []string{workingDir, filepath.Dir(executable)} {
		root, err := filepath.Abs(start)
		if err != nil {
			continue
		}
		for {
			script = filepath.Join(root, "src", "backend", "diffuchat.py")
			if info, err := os.Stat(script); err == nil && !info.IsDir() {
				candidates := []string{os.Getenv("GEPHID_PYTHON"), filepath.Join(root, ".venv", "bin", "python3"), filepath.Join(root, ".venv", "bin", "python")}
				if virtualEnv := os.Getenv("VIRTUAL_ENV"); virtualEnv != "" {
					candidates = append(candidates, filepath.Join(virtualEnv, "bin", "python3"))
				}
				candidates = append(candidates, "python3")
				for _, candidate := range candidates {
					if candidate == "" {
						continue
					}
					if resolved, err := exec.LookPath(candidate); err == nil && executableFile(resolved) {
						return resolved, script, nil
					}
					if candidate == os.Getenv("GEPHID_PYTHON") {
						return "", "", fmt.Errorf("GEPHID_PYTHON non eseguibile: %s", candidate)
					}
				}
				return "", "", fmt.Errorf("Python non trovato; crea .venv nel checkout o imposta GEPHID_PYTHON")
			}
			parent := filepath.Dir(root)
			if parent == root {
				break
			}
			root = parent
		}
	}
	return "", "", fmt.Errorf("backend non trovato; avvia il launcher dal checkout oppure ricostruisci la .app con build.sh")
}

func backendPath() string {
	paths := filepath.SplitList(os.Getenv("PATH"))
	paths = append(paths, "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")
	seen := make(map[string]bool)
	var out []string
	for _, path := range paths {
		if path != "" && filepath.IsAbs(path) && !seen[path] {
			out = append(out, path)
			seen[path] = true
		}
	}
	return strings.Join(out, string(os.PathListSeparator))
}

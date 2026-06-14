// Gephid.app — guscio nativo macOS (WKWebView) per la chat Gephid.
// Avvia il backend Python (diffuchat.py nel venv mlx-vlm), aspetta che sia pronto,
// apre la finestra nativa, e alla chiusura spegne il backend.
package main

/*
#cgo CFLAGS: -x objective-c -fobjc-arc
#cgo LDFLAGS: -framework Cocoa -framework Speech -framework AVFoundation
#import <Cocoa/Cocoa.h>
#import <Speech/Speech.h>
#import <AVFoundation/AVFoundation.h>
#include <stdlib.h>
// Installa il menu "Modifica" standard: senza, in WKWebView Cmd+C/V/X/A non funzionano
static void installEditMenu(void) {
  NSMenu *mainMenu = [[NSMenu alloc] init];
  NSMenuItem *appItem = [[NSMenuItem alloc] init];
  [mainMenu addItem:appItem];
  NSMenu *appMenu = [[NSMenu alloc] init];
  [appMenu addItemWithTitle:@"Nascondi" action:@selector(hide:) keyEquivalent:@"h"];
  [appMenu addItemWithTitle:@"Esci" action:@selector(terminate:) keyEquivalent:@"q"];
  [appItem setSubmenu:appMenu];
  NSMenuItem *editItem = [[NSMenuItem alloc] init];
  [mainMenu addItem:editItem];
  NSMenu *editMenu = [[NSMenu alloc] initWithTitle:@"Modifica"];
  [editMenu addItemWithTitle:@"Annulla" action:@selector(undo:) keyEquivalent:@"z"];
  NSMenuItem *r = [editMenu addItemWithTitle:@"Ripeti" action:@selector(redo:) keyEquivalent:@"z"];
  [r setKeyEquivalentModifierMask:(NSEventModifierFlagCommand|NSEventModifierFlagShift)];
  [editMenu addItem:[NSMenuItem separatorItem]];
  [editMenu addItemWithTitle:@"Taglia" action:@selector(cut:) keyEquivalent:@"x"];
  [editMenu addItemWithTitle:@"Copia" action:@selector(copy:) keyEquivalent:@"c"];
  [editMenu addItemWithTitle:@"Incolla" action:@selector(paste:) keyEquivalent:@"v"];
  [editMenu addItemWithTitle:@"Seleziona tutto" action:@selector(selectAll:) keyEquivalent:@"a"];
  [editMenu addItem:[NSMenuItem separatorItem]];
  [editMenu addItemWithTitle:@"Avvia/Ferma dettatura" action:@selector(startDictation:) keyEquivalent:@""];
  [editItem setSubmenu:editMenu];
  [NSApp setMainMenu:mainMenu];
}
// ---- Riconoscimento vocale on-device (offline) via Speech framework ----
// La dettatura di sistema non inserisce testo in WKWebView; quindi trascriviamo noi
// e scriviamo il risultato nella textarea via JS (polling di gephidDictText).
static SFSpeechRecognizer *g_recog = nil;
static SFSpeechAudioBufferRecognitionRequest *g_req = nil;
static SFSpeechRecognitionTask *g_task = nil;
static AVAudioEngine *g_engine = nil;
static NSString *g_final = nil;    // segmenti già conclusi (accumulati)
static NSString *g_partial = nil;  // segmento in corso (parziale)
static NSLock *g_lock = nil;
static long g_epoch = 0;           // invalida i task vecchi (riavvio/reset/stop)

static void gephidDictInit(void) {
  g_lock = [[NSLock alloc] init];
  g_final = @""; g_partial = @"";
  [SFSpeechRecognizer requestAuthorization:^(SFSpeechRecognizerAuthorizationStatus s){}];
}
// Avvia un segmento di riconoscimento; al silenzio (isFinal) accumula e ne riavvia uno nuovo
// -> dettatura continua che non si azzera dopo le pause. L'epoch scarta i task obsoleti.
static void startSegment(void) {
  [g_lock lock]; long myEpoch = ++g_epoch; [g_lock unlock];
  SFSpeechAudioBufferRecognitionRequest *r = [[SFSpeechAudioBufferRecognitionRequest alloc] init];
  r.shouldReportPartialResults = YES;
  if ([g_recog supportsOnDeviceRecognition]) r.requiresOnDeviceRecognition = YES;
  [g_lock lock]; g_req = r; [g_lock unlock];
  g_task = [g_recog recognitionTaskWithRequest:r resultHandler:^(SFSpeechRecognitionResult *res, NSError *e){
    [g_lock lock]; BOOL current = (myEpoch == g_epoch); [g_lock unlock];
    if (!current) return; // task obsoleto (reset/stop/riavvio): ignora
    if (res) {
      NSString *seg = [[res bestTranscription] formattedString];
      [g_lock lock]; g_partial = seg ? seg : @""; [g_lock unlock];
      if ([res isFinal]) {
        [g_lock lock];
        if (g_partial.length) g_final = [NSString stringWithFormat:@"%@%@%@", g_final, (g_final.length ? @" " : @""), g_partial];
        g_partial = @"";
        [g_lock unlock];
        if (g_engine) startSegment(); // continua oltre la pausa
      }
    } else if (e) {
      // timeout/silenzio: salva il parziale corrente prima di riavviare (altrimenti si perde)
      [g_lock lock];
      if (g_partial.length) g_final = [NSString stringWithFormat:@"%@%@%@", g_final, (g_final.length ? @" " : @""), g_partial];
      g_partial = @"";
      [g_lock unlock];
      if (g_engine) startSegment(); // riprova finché il mic è attivo
    }
  }];
}
// 0 = ok, -1 = recognizer non disponibile, -2 = microfono/audio non avviabile
static int gephidDictStart(void) {
  if (!g_lock) gephidDictInit();
  [g_lock lock]; g_final = @""; g_partial = @""; [g_lock unlock];
  if (g_engine) return 0; // già attivo
  if ([SFSpeechRecognizer authorizationStatus] != SFSpeechRecognizerAuthorizationStatusAuthorized) {
    [SFSpeechRecognizer requestAuthorization:^(SFSpeechRecognizerAuthorizationStatus s){}];
  }
  NSLocale *loc = [NSLocale localeWithLocaleIdentifier:@"it-IT"];
  g_recog = [[SFSpeechRecognizer alloc] initWithLocale:loc];
  if (!g_recog) g_recog = [[SFSpeechRecognizer alloc] init];
  if (!g_recog || ![g_recog isAvailable]) return -1;
  g_engine = [[AVAudioEngine alloc] init];
  AVAudioInputNode *input = [g_engine inputNode];
  AVAudioFormat *fmt = [input outputFormatForBus:0];
  if (!fmt || [fmt sampleRate] <= 0 || [fmt channelCount] == 0) { g_engine = nil; return -2; }
  [input installTapOnBus:0 bufferSize:1024 format:fmt block:^(AVAudioPCMBuffer *buf, AVAudioTime *when){
    [g_lock lock]; SFSpeechAudioBufferRecognitionRequest *r = g_req; [g_lock unlock]; // pointer sotto lock (no use-after-free al riavvio)
    if (r) [r appendAudioPCMBuffer:buf];
  }];
  [g_engine prepare];
  NSError *err = nil;
  if (![g_engine startAndReturnError:&err]) { g_engine = nil; return -2; }
  startSegment();
  return 0;
}
static void gephidDictReset(void) {
  // svuota e invalida il task corrente (++epoch) prima di cancellarlo, così l'enunciato
  // in corso non viene ri-riportato; poi riavvia un segmento pulito.
  [g_lock lock]; g_final = @""; g_partial = @""; ++g_epoch;
  SFSpeechAudioBufferRecognitionRequest *r = g_req; g_req = nil;
  SFSpeechRecognitionTask *t = g_task; g_task = nil; [g_lock unlock];
  if (t) [t cancel];
  if (r) [r endAudio];
  if (g_engine) startSegment();
}
static void gephidDictStop(void) {
  if (g_engine) { [g_engine stop]; [[g_engine inputNode] removeTapOnBus:0]; g_engine = nil; }
  [g_lock lock]; ++g_epoch;
  SFSpeechAudioBufferRecognitionRequest *r = g_req; g_req = nil;
  SFSpeechRecognitionTask *t = g_task; g_task = nil; [g_lock unlock];
  if (r) [r endAudio];
  if (t) [t cancel];
}
static const char* gephidDictText(void) {
  [g_lock lock];
  NSString *t = [NSString stringWithFormat:@"%@%@%@", g_final ? g_final : @"", (g_final.length && g_partial.length) ? @" " : @"", g_partial ? g_partial : @""];
  const char* c = strdup([t UTF8String]);
  [g_lock unlock];
  return c;
}
// Pannello file nativo (WKWebView non apre il file picker da <input type=file> senza delegate).
// Ritorna i path scelti separati da newline (stringa vuota se annullato).
static const char* gephidOpenFiles(void) {
  NSOpenPanel *panel = [NSOpenPanel openPanel];
  [panel setAllowsMultipleSelection:YES];
  [panel setCanChooseDirectories:NO];
  [panel setCanChooseFiles:YES];
  NSString *joined = @"";
  if ([panel runModal] == NSModalResponseOK) {
    NSMutableArray *paths = [NSMutableArray array];
    for (NSURL *url in [panel URLs]) { [paths addObject:[url path]]; }
    joined = [paths componentsJoinedByString:@"\n"];
  }
  return strdup([joined UTF8String]);
}
// Selettore di cartella (per scegliere una cartella-modello MLX locale).
static const char* gephidOpenDir(void) {
  NSOpenPanel *panel = [NSOpenPanel openPanel];
  [panel setAllowsMultipleSelection:NO];
  [panel setCanChooseDirectories:YES];
  [panel setCanChooseFiles:NO];
  NSString *res = @"";
  if ([panel runModal] == NSModalResponseOK && [[panel URLs] count] > 0) {
    res = [[[panel URLs] objectAtIndex:0] path];
  }
  return strdup([res UTF8String]);
}
// Pannello di salvataggio nativo: l'utente sceglie nome e cartella. Ritorna il path (vuoto se annullato).
static const char* gephidSaveFile(const char* defName) {
  NSSavePanel *panel = [NSSavePanel savePanel];
  if (defName) [panel setNameFieldStringValue:[NSString stringWithUTF8String:defName]];
  NSString *res = @"";
  if ([panel runModal] == NSModalResponseOK) { res = [[panel URL] path]; }
  return strdup([res UTF8String]);
}
*/
import "C"

import (
	"encoding/json"
	"fmt"
	"html"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
	"unsafe"

	webview "github.com/webview/webview_go"
)

// Derivati dalla porta (letta dallo stesso config.json del backend, così sono sempre d'accordo).
var backendURL = "http://localhost:8890/"
var healthURL = "http://localhost:8890/api/health"
var backendAddr = "127.0.0.1:8890"

func initPort(home string) {
	port := 8890
	if b, err := os.ReadFile(filepath.Join(home, ".config", "diffuchat", "config.json")); err == nil {
		var c struct {
			Port int `json:"port"`
		}
		if json.Unmarshal(b, &c) == nil && c.Port > 0 && c.Port < 65536 {
			port = c.Port
		}
	}
	backendURL = fmt.Sprintf("http://localhost:%d/", port)
	healthURL = fmt.Sprintf("http://localhost:%d/api/health", port)
	backendAddr = fmt.Sprintf("127.0.0.1:%d", port)
}

// portOpen: qualcuno ascolta già sulla porta (anche se non risponde ancora HTTP)?
// Serve per non avviare un secondo backend che non riuscirebbe a fare bind.
func portOpen() bool {
	c, err := net.DialTimeout("tcp", backendAddr, 700*time.Millisecond)
	if err != nil {
		return false
	}
	c.Close()
	return true
}

// checkHealth: (raggiungibile, modello caricato, eventuale errore del modello).
func checkHealth() (bool, bool, string) {
	c := http.Client{Timeout: 1500 * time.Millisecond}
	r, err := c.Get(healthURL)
	if err != nil {
		return false, false, ""
	}
	defer r.Body.Close()
	if r.StatusCode != 200 {
		return false, false, ""
	}
	var h struct {
		ModelOK  bool   `json:"model_ok"`
		ModelErr string `json:"model_err"`
	}
	if json.NewDecoder(r.Body).Decode(&h) != nil {
		return true, false, ""
	}
	return true, h.ModelOK, h.ModelErr
}

// safeDispatch: evita di chiamare la webview dopo che la finestra è stata chiusa.
func safeDispatch(w webview.WebView, closed <-chan struct{}, f func()) {
	select {
	case <-closed:
		return
	default:
		w.Dispatch(f)
	}
}

const logoSVG = `<svg viewBox="0 0 512 512" width="76" height="76" xmlns="http://www.w3.org/2000/svg"><rect x="40" y="40" width="432" height="432" rx="104" fill="#4169E1"/><g transform="rotate(13.37 256 256)" fill="#fff"><ellipse cx="254" cy="210" rx="58" ry="52"/><path d="M247 250 L266 250 L302 372 Q307 391 287 388 L227 378 Q213 376 219 359 Z"/></g></svg>`

func page(title, msg string, spin bool) string {
	sp := ""
	if spin {
		sp = `<div class="sp"></div>`
	}
	return `<!DOCTYPE html><html><head><meta charset="utf-8"><style>
	html,body{height:100%;margin:0}
	body{background:#0b0e14;color:#e6edf3;font-family:-apple-system,'Segoe UI',sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:18px;padding:40px}
	.t{font-size:1.35rem;font-weight:600}.m{color:#8b98a5;max-width:540px;line-height:1.6}
	.sp{width:34px;height:34px;border:3px solid #1c2333;border-top-color:#4169e1;border-radius:50%;animation:s 1s linear infinite}
	@keyframes s{to{transform:rotate(360deg)}} code{background:#141925;padding:2px 7px;border-radius:6px;color:#4169e1}
	</style></head><body>` + logoSVG + `<div class="t">` + title + `</div>` + sp + `<div class="m">` + msg + `</div></body></html>`
}

func main() {
	// Runtime embeddato nella .app (Contents/Resources/python + diffuchat.py).
	// Così l'app è self-contained: niente dipendenza dal venv esterno.
	exe, _ := os.Executable()
	home, _ := os.UserHomeDir()
	initPort(home) // porta dal config.json (uguale a quella del backend)
	res := filepath.Join(filepath.Dir(exe), "..", "Resources")
	py := filepath.Join(res, "python", "bin", "python3")
	script := filepath.Join(res, "diffuchat.py")
	if _, err := os.Stat(py); err != nil { // fallback dev (go run, fuori dal bundle)
		py = home + "/.venv-mlxvlm/bin/python"
		script = home + "/Desktop/AI/Gephid/src/backend/diffuchat.py"
	}

	var cmd *exec.Cmd
	procDied := make(chan error, 1)
	// Avvio il backend solo se la porta è libera. Se è già occupata (istanza
	// esistente o in boot), la riuso e non la killo all'uscita (cmd resta nil).
	if !portOpen() {
		if _, err := os.Stat(py); err != nil {
			w := webview.New(false)
			w.SetTitle("Gephid — configurazione mancante")
			w.SetSize(640, 380, webview.HintNone)
			w.SetHtml(page("Runtime non trovato",
				"Non trovo <code>"+html.EscapeString(py)+"</code>.<br><br>Crealo da Terminale con:<br><br><code>python3 -m venv ~/.venv-mlxvlm</code><br><code>~/.venv-mlxvlm/bin/pip install mlx-vlm</code>", false))
			w.Run()
			w.Destroy()
			return
		}
		cmd = exec.Command(py, script)
		cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true} // gruppo proprio → killabile coi figli
		// Ambiente pulito: lanciata via .app, l'env "ricco" di launchd fa impallare
		// l'avvio dell'interprete Python. Un env minimale lo fa partire regolarmente.
		cmd.Env = []string{
			"HOME=" + home,
			"PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
			"TMPDIR=" + os.TempDir(),
			"HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1", "TOKENIZERS_PARALLELISM=false",
		}
		// I log del backend finiscono in un file (lanciata via .app non c'è un terminale)
		if lf, err := os.Create(filepath.Join(home, "gephid-backend.log")); err == nil {
			cmd.Stdout = lf
			cmd.Stderr = lf
		} else {
			cmd.Stdout = os.Stdout
			cmd.Stderr = os.Stderr
		}
		if err := cmd.Start(); err != nil { // non ingoiare l'errore di avvio
			w := webview.New(false)
			w.SetTitle("Gephid — avvio fallito")
			w.SetSize(640, 380, webview.HintNone)
			w.SetHtml(page("Avvio backend fallito",
				"Non riesco ad avviare il backend Python:<br><br><code>"+html.EscapeString(err.Error())+"</code>", false))
			w.Run()
			w.Destroy()
			return
		}
		go func() { procDied <- cmd.Wait() }() // segnala se il processo muore prima del pronto
	}

	w := webview.New(false)
	defer w.Destroy()
	C.installEditMenu() // menu nativo: nome app, Esci (Cmd+Q), Modifica (Cmd C/V/X/A/Z)
	// NB: nessuna richiesta permessi all'avvio. Vengono chiesti solo al primo uso del microfono
	// (gephidDictStart), e solo se l'utente ha abilitato la dettatura nelle Impostazioni.
	w.Bind("gephidDictStart", func() int { return int(C.gephidDictStart()) }) // avvia dettatura on-device
	w.Bind("gephidDictStop", func() { C.gephidDictStop() })
	w.Bind("gephidDictReset", func() { C.gephidDictReset() })
	w.Bind("gephidDictText", func() string { cs := C.gephidDictText(); s := C.GoString(cs); C.free(unsafe.Pointer(cs)); return s })
	w.Bind("gephidOpenFiles", func() string { // pannello file nativo (WKWebView non lo apre da solo)
		cs := C.gephidOpenFiles()
		s := C.GoString(cs)
		C.free(unsafe.Pointer(cs))
		return s
	})
	w.Bind("gephidOpenDir", func() string { // selettore cartella (modello locale)
		cs := C.gephidOpenDir()
		s := C.GoString(cs)
		C.free(unsafe.Pointer(cs))
		return s
	})
	w.Bind("gephidSaveFile", func(name string) string { // pannello di salvataggio nativo
		cn := C.CString(name)
		cs := C.gephidSaveFile(cn)
		s := C.GoString(cs)
		C.free(unsafe.Pointer(cn))
		C.free(unsafe.Pointer(cs))
		return s
	})
	w.SetTitle("Gephid")
	w.SetSize(980, 820, webview.HintNone)
	w.SetHtml(page("Carico Gephid…",
		"Il modello a diffusione si sta caricando (~15-30s al primo avvio).<br>Si prega di attendere per cortesia.", true))

	closed := make(chan struct{})
	go func() {
		deadline := time.Now().Add(120 * time.Second) // tetto basato su orologio reale
		for time.Now().Before(deadline) {
			select {
			case err := <-procDied: // il backend è morto prematuramente
				msg := "Il backend Python si è chiuso inaspettatamente."
				if err != nil {
					msg += "<br><br><code>" + html.EscapeString(err.Error()) + "</code>"
				}
				msg += "<br><br>Controlla i log nel Terminale."
				safeDispatch(w, closed, func() { w.SetHtml(page("Backend terminato", msg, false)) })
				return
			case <-closed:
				return
			default:
			}
			reachable, _, _ := checkHealth() // la UI è servita dal backend; gli errori del modello compaiono in chat o nelle Impostazioni
			if reachable {
				safeDispatch(w, closed, func() { w.Navigate(backendURL) })
				return
			}
			time.Sleep(1 * time.Second)
		}
		safeDispatch(w, closed, func() {
			w.SetHtml(page("Backend non pronto",
				"Gephid non si è avviata entro 120s. Chiudi e riprova, o controlla i log.", false))
		})
	}()

	w.Run() // blocca finché non chiudi la finestra
	close(closed)

	if cmd != nil && cmd.Process != nil {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) // spegni backend + figli (solo se l'ho avviato io)
	}
	fmt.Println("Gephid: finestra chiusa, backend spento.")
}

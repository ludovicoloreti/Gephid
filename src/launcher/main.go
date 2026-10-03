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
// Lingua dei testi nativi (menu, schermate di avvio): quella di macOS.
static int gephidIsItalian(void) {
  NSString *l = [[NSLocale preferredLanguages] firstObject];
  return (l && [l hasPrefix:@"it"]) ? 1 : 0;
}
// Azioni di menu verso la pagina: il menu le accoda qui, Go le preleva (polling) e chiama
// gephidMenu('azione') nella webview. Niente //export cgo: con un preambolo che DEFINISCE funzioni
// cgo non lo consente, e una coda di una voce basta (nessuno clicca due menu in 100ms).
static char g_menu_action[32] = {0};
static NSLock *g_menu_lock = nil;
@interface GephidMenuTarget : NSObject
- (void)menuAction:(id)sender;
@end
@implementation GephidMenuTarget
- (void)menuAction:(id)sender {
  NSString *a = [sender representedObject];
  if (!a) return;
  [g_menu_lock lock];
  strlcpy(g_menu_action, [a UTF8String], sizeof(g_menu_action));
  [g_menu_lock unlock];
}
@end
static GephidMenuTarget *g_menu_target = nil;
static const char* gephidPopMenuAction(void) {
  if (!g_menu_lock) return strdup("");
  [g_menu_lock lock];
  const char *c = strdup(g_menu_action);
  g_menu_action[0] = 0;
  [g_menu_lock unlock];
  return c;
}
static NSMenuItem* addAct(NSMenu *m, NSString *title, NSString *action, NSString *key, NSEventModifierFlags mods) {
  NSMenuItem *it = [m addItemWithTitle:title action:@selector(menuAction:) keyEquivalent:key];
  [it setTarget:g_menu_target];
  [it setRepresentedObject:action];
  if (mods) [it setKeyEquivalentModifierMask:mods];
  return it;
}
// Menu nativo completo e bilingue. Senza il menu "Modifica", in WKWebView Cmd+C/V/X/A non funzionano.
static void installMenus(void) {
  int it = gephidIsItalian();
  g_menu_lock = [[NSLock alloc] init];
  g_menu_target = [[GephidMenuTarget alloc] init];
  NSEventModifierFlags cmd = NSEventModifierFlagCommand, cmdShift = NSEventModifierFlagCommand|NSEventModifierFlagShift;
  NSMenu *mainMenu = [[NSMenu alloc] init];
  // App
  NSMenuItem *appItem = [[NSMenuItem alloc] init]; [mainMenu addItem:appItem];
  NSMenu *appMenu = [[NSMenu alloc] init];
  [appMenu addItemWithTitle:(it ? @"Informazioni su Gephid" : @"About Gephid") action:@selector(orderFrontStandardAboutPanel:) keyEquivalent:@""];
  [appMenu addItem:[NSMenuItem separatorItem]];
  addAct(appMenu, (it ? @"Impostazioni…" : @"Settings…"), @"settings", @",", cmd);
  [appMenu addItem:[NSMenuItem separatorItem]];
  [appMenu addItemWithTitle:(it ? @"Nascondi Gephid" : @"Hide Gephid") action:@selector(hide:) keyEquivalent:@"h"];
  [appMenu addItemWithTitle:(it ? @"Esci da Gephid" : @"Quit Gephid") action:@selector(terminate:) keyEquivalent:@"q"];
  [appItem setSubmenu:appMenu];
  // File
  NSMenuItem *fileItem = [[NSMenuItem alloc] init]; [mainMenu addItem:fileItem];
  NSMenu *fileMenu = [[NSMenu alloc] initWithTitle:@"File"];
  addAct(fileMenu, (it ? @"Nuova chat" : @"New Chat"), @"new", @"n", cmd);
  addAct(fileMenu, (it ? @"Allega file…" : @"Attach Files…"), @"attach", @"o", cmd);
  [fileMenu addItem:[NSMenuItem separatorItem]];
  addAct(fileMenu, (it ? @"Salva chat" : @"Save Chat"), @"save", @"s", cmd);
  addAct(fileMenu, (it ? @"Chat salvate…" : @"Saved Chats…"), @"saved", @"o", cmdShift);
  addAct(fileMenu, (it ? @"Esporta…" : @"Export…"), @"export", @"e", cmd);
  [fileMenu addItem:[NSMenuItem separatorItem]];
  [fileMenu addItemWithTitle:(it ? @"Chiudi finestra" : @"Close Window") action:@selector(performClose:) keyEquivalent:@"w"];
  [fileItem setSubmenu:fileMenu];
  // Modifica
  NSMenuItem *editItem = [[NSMenuItem alloc] init]; [mainMenu addItem:editItem];
  NSMenu *editMenu = [[NSMenu alloc] initWithTitle:(it ? @"Modifica" : @"Edit")];
  [editMenu addItemWithTitle:(it ? @"Annulla" : @"Undo") action:@selector(undo:) keyEquivalent:@"z"];
  NSMenuItem *r = [editMenu addItemWithTitle:(it ? @"Ripeti" : @"Redo") action:@selector(redo:) keyEquivalent:@"z"];
  [r setKeyEquivalentModifierMask:cmdShift];
  [editMenu addItem:[NSMenuItem separatorItem]];
  [editMenu addItemWithTitle:(it ? @"Taglia" : @"Cut") action:@selector(cut:) keyEquivalent:@"x"];
  [editMenu addItemWithTitle:(it ? @"Copia" : @"Copy") action:@selector(copy:) keyEquivalent:@"c"];
  [editMenu addItemWithTitle:(it ? @"Incolla" : @"Paste") action:@selector(paste:) keyEquivalent:@"v"];
  [editMenu addItemWithTitle:(it ? @"Seleziona tutto" : @"Select All") action:@selector(selectAll:) keyEquivalent:@"a"];
  [editItem setSubmenu:editMenu];
  // Vista
  NSMenuItem *viewItem = [[NSMenuItem alloc] init]; [mainMenu addItem:viewItem];
  NSMenu *viewMenu = [[NSMenu alloc] initWithTitle:(it ? @"Vista" : @"View")];
  addAct(viewMenu, (it ? @"Testo più grande" : @"Bigger Text"), @"bigger", @"+", cmd);
  addAct(viewMenu, (it ? @"Testo più piccolo" : @"Smaller Text"), @"smaller", @"-", cmd);
  [viewMenu addItem:[NSMenuItem separatorItem]];
  addAct(viewMenu, (it ? @"Ragiona prima di rispondere" : @"Think Before Answering"), @"think", @"r", cmdShift);
  addAct(viewMenu, (it ? @"Agente (strumenti locali)" : @"Agent (Local Tools)"), @"agent", @"a", cmdShift);
  [viewItem setSubmenu:viewMenu];
  // Finestra
  NSMenuItem *winItem = [[NSMenuItem alloc] init]; [mainMenu addItem:winItem];
  NSMenu *winMenu = [[NSMenu alloc] initWithTitle:(it ? @"Finestra" : @"Window")];
  [winMenu addItemWithTitle:(it ? @"Contrai" : @"Minimize") action:@selector(performMiniaturize:) keyEquivalent:@"m"];
  [winMenu addItemWithTitle:(it ? @"Ridimensiona" : @"Zoom") action:@selector(performZoom:) keyEquivalent:@""];
  [winItem setSubmenu:winMenu];
  [NSApp setWindowsMenu:winMenu];
  [NSApp setMainMenu:mainMenu];
}
// La finestra ricorda dimensione e posizione tra un avvio e l'altro (frame salvato da AppKit).
static void gephidSetupWindow(void *win) {
  NSWindow *w = (__bridge NSWindow *)win;
  if (!w) return;
  [w setMinSize:NSMakeSize(560, 480)];
  [w setFrameAutosaveName:@"GephidMainWindow"];
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
// "sto registrando": flag scalare, NON il puntatore g_engine. I callback del recognizer girano su
// una coda del framework Speech: leggere lì g_engine (static strong, ARC) mentre il main thread lo
// azzera fa fare a ARC un retain su un oggetto in deallocazione -> crash. Un int non ha questo
// problema, e non richiede di tenere il lock attorno a [g_engine stop] (che aspetta il tap audio,
// il quale prende g_lock: si deadlockerebbe).
static volatile int g_running = 0;

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
  // il task va pubblicato SOTTO LOCK: gephidDictStop/Reset lo leggono sotto lock per cancellarlo,
  // e questa assegnazione può arrivare dalla coda del recognizer (riavvio di segmento).
  SFSpeechRecognitionTask *t = [g_recog recognitionTaskWithRequest:r resultHandler:^(SFSpeechRecognitionResult *res, NSError *e){
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
        if (g_running) startSegment(); // continua oltre la pausa
      }
    } else if (e) {
      // timeout/silenzio: salva il parziale corrente prima di riavviare (altrimenti si perde)
      [g_lock lock];
      if (g_partial.length) g_final = [NSString stringWithFormat:@"%@%@%@", g_final, (g_final.length ? @" " : @""), g_partial];
      g_partial = @"";
      [g_lock unlock];
      // riavvia con un piccolo backoff (evita lo spin se il recognizer erra di continuo)
      if (g_running) dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(120 * NSEC_PER_MSEC)), dispatch_get_main_queue(), ^{ if (g_running) startSegment(); });
    }
  }];
  [g_lock lock]; g_task = t; [g_lock unlock];
}
// 0 = ok · -1 = recognizer non disponibile · -2 = microfono/audio non avviabile
// -3 = permesso non ancora deciso (richiesto ora: approvarlo e riprovare) · -4 = permesso negato
static int gephidDictStart(const char *locale) {
  if (!g_lock) gephidDictInit();
  [g_lock lock]; g_final = @""; g_partial = @""; [g_lock unlock];
  if (g_running) return 0; // già attivo
  // permesso riconoscimento vocale
  SFSpeechRecognizerAuthorizationStatus sa = [SFSpeechRecognizer authorizationStatus];
  if (sa == SFSpeechRecognizerAuthorizationStatusNotDetermined) {
    [SFSpeechRecognizer requestAuthorization:^(SFSpeechRecognizerAuthorizationStatus s){}];
    return -3;
  }
  if (sa == SFSpeechRecognizerAuthorizationStatusDenied || sa == SFSpeechRecognizerAuthorizationStatusRestricted) return -4;
  // permesso microfono (separato dal riconoscimento vocale)
  AVAuthorizationStatus ma = [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio];
  if (ma == AVAuthorizationStatusNotDetermined) {
    [AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio completionHandler:^(BOOL g){}];
    return -3;
  }
  if (ma == AVAuthorizationStatusDenied || ma == AVAuthorizationStatusRestricted) return -4;
  // lingua della UI (prima era fissa in it-IT anche con l'interfaccia in inglese)
  NSString *lid = (locale && locale[0]) ? [NSString stringWithUTF8String:locale] : @"it-IT";
  NSLocale *loc = [NSLocale localeWithLocaleIdentifier:lid];
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
  g_running = 1;   // prima di startSegment: i riavvii di segmento lo consultano
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
  if (g_running) startSegment();
}
static void gephidDictStop(void) {
  g_running = 0;   // PRIMA di fermare il motore: nessun callback in volo riavvia un altro segmento
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
	"strconv"
	"strings"
	"sync"
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

// otherLaunchersAlive: esistono ALTRE finestre Gephid (launcher) oltre a me?
// Serve per non uccidere il backend condiviso quando si chiude una finestra mentre altre sono aperte.
func otherLaunchersAlive() bool {
	out, err := exec.Command("pgrep", "-f", "Gephid.app/Contents/MacOS/Gephid").Output()
	if err != nil {
		return false
	}
	self := os.Getpid()
	for _, f := range strings.Fields(string(out)) {
		if pid, e := strconv.Atoi(f); e == nil && pid != 0 && pid != self {
			if syscall.Kill(pid, 0) == nil { // ancora vivo
				return true
			}
		}
	}
	return false
}

// killBackend: spegne il backend che HO avviato io (gruppo di processi). Mai un kill "per porta":
// ucciderebbe un backend che un'altra finestra potrebbe aver adottato.
func killBackend(cmd *exec.Cmd) {
	if cmd != nil && cmd.Process != nil {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	// i programmi lanciati dall'agente hanno un gruppo di processi proprio (per poterli fermare coi
	// figli): il kill del gruppo del backend non li raggiunge. La loro cartella ha prefisso gephid-run-.
	_ = exec.Command("pkill", "-9", "-f", "gephid-run-").Run()
}

// startBackend avvia il backend Python come sottoprocesso: gruppo proprio (killabile coi figli),
// env pulito (l'env "ricco" di launchd fa impallare l'interprete), log in append su ~/Library/Logs/Gephid/backend.log.
// Ritorna il comando e un canale che riceve l'esito quando il processo muore.
func startBackend(py, script, home string) (*exec.Cmd, chan error, error) {
	cmd := exec.Command(py, script)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Env = []string{
		"HOME=" + home,
		"PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
		"TMPDIR=" + os.TempDir(),
		"HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1", "TOKENIZERS_PARALLELISM=false",
	}
	// log nella posizione standard di macOS (prima in ~/gephid-backend.log, in mezzo alla home)
	logDir := filepath.Join(home, "Library", "Logs", "Gephid")
	_ = os.MkdirAll(logDir, 0755)
	logPath := filepath.Join(logDir, "backend.log")
	// rotazione: il log è in append e non veniva mai potato — oltre i 5MB ruota su .old
	if st, err := os.Stat(logPath); err == nil && st.Size() > 5*1024*1024 {
		_ = os.Rename(logPath, logPath+".old")
	}
	if lf, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644); err == nil {
		cmd.Stdout = lf
		cmd.Stderr = lf
	} else {
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
	}
	if err := cmd.Start(); err != nil {
		return nil, nil, err
	}
	died := make(chan error, 1)
	go func() { died <- cmd.Wait() }()
	return cmd, died, nil
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

// tx: testo nella lingua di macOS (le schermate native compaiono prima che la pagina sappia la lingua)
func tx(it, en string) string {
	if C.gephidIsItalian() != 0 {
		return it
	}
	return en
}

// lucchetto del brand (line-art, inclinato −13.37°) — stesso della UI e della materializzazione
const logoSVG = `<svg width="62" height="62" viewBox="0 0 24 24" fill="none"><path d="M8 10V7a4 4 0 0 1 8 0v3" stroke="#4169E1" stroke-width="2.1" stroke-linecap="round"></path><rect x="4.6" y="10" width="14.8" height="9.6" rx="3" fill="#4169E1"></rect><circle cx="12" cy="14.4" r="1.5" fill="#070a10"></circle></svg>`

// Loader nativo: UN solo linguaggio visivo con la materializzazione della pagina (sfondo scuro + lucchetto
// che pulsa, niente spinner circolare). Fa solo da fade verso la materializzazione (griglia 4×4 + %).
func page(title, msg string, spin bool) string {
	pulse := ""
	if spin {
		pulse = " pulsing"
	}
	return `<!DOCTYPE html><html><head><meta charset="utf-8"><style>
	html,body{height:100%;margin:0}
	body{background:#070a10;color:#e6edf3;font-family:-apple-system,'Segoe UI',sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:16px;padding:40px}
	.lk{display:inline-flex;transform:rotate(-13.37deg);filter:drop-shadow(0 0 18px rgba(65,105,225,.6))}
	.lk.pulsing{animation:pulse 1.7s ease-in-out infinite}
	@keyframes pulse{0%,100%{filter:drop-shadow(0 0 12px rgba(65,105,225,.45))}50%{filter:drop-shadow(0 0 34px rgba(65,105,225,1))}}
	.t{font-size:1.18rem;font-weight:700;letter-spacing:-.01em}
	.m{color:#7f8b9a;max-width:540px;line-height:1.6;font-size:.9rem}
	.tk{margin-top:8px;font-family:'Courier New',monospace;font-size:.72rem;letter-spacing:.1em;color:#3DF9A6}
	code{background:#10182a;padding:2px 7px;border-radius:6px;color:#8ab0ff;font-family:'Courier New',monospace}
	@media (prefers-color-scheme: light){
	  body{background:#f4f6f9;color:#1a2230}
	  .m{color:#5b6675}
	  .tk{color:#067a45}
	  code{background:#e9edf3;color:#2f4fc0}
	}
	</style></head><body><span class="lk` + pulse + `">` + logoSVG + `</span><div class="t">` + title + `</div><div class="m">` + msg + `</div><div class="tk">NO-NET · 0xLOCAL · ` + tx("NESSUN BYTE ESCE", "NO BYTE LEAVES") + `</div></body></html>`
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

	var bmu sync.Mutex // protegge cmd (il backend corrente può cambiare se viene riavviato)
	var cmd *exec.Cmd
	var procDied chan error
	iStartedIt := false
	// Avvio il backend solo se la porta è libera. Se è già occupata (istanza
	// esistente o in boot), la riuso e non la supervisiono: non è mia.
	if !portOpen() {
		if _, err := os.Stat(py); err != nil {
			w := webview.New(false)
			w.SetTitle(tx("Gephid — configurazione mancante", "Gephid — missing setup"))
			w.SetSize(640, 380, webview.HintNone)
			w.SetHtml(page(tx("Runtime non trovato", "Runtime not found"),
				tx("Non trovo", "Can't find")+" <code>"+html.EscapeString(py)+"</code>.<br><br>"+tx("Crealo da Terminale con:", "Create it from Terminal with:")+"<br><br><code>python3 -m venv ~/.venv-mlxvlm</code><br><code>~/.venv-mlxvlm/bin/pip install mlx-vlm</code>", false))
			w.Run()
			w.Destroy()
			return
		}
		c, died, err := startBackend(py, script, home)
		if err != nil { // non ingoiare l'errore di avvio
			w := webview.New(false)
			w.SetTitle(tx("Gephid — avvio fallito", "Gephid — startup failed"))
			w.SetSize(640, 380, webview.HintNone)
			w.SetHtml(page(tx("Avvio backend fallito", "Backend failed to start"),
				tx("Non riesco ad avviare il backend Python:", "Can't start the Python backend:")+"<br><br><code>"+html.EscapeString(err.Error())+"</code>", false))
			w.Run()
			w.Destroy()
			return
		}
		cmd, procDied, iStartedIt = c, died, true
	}

	w := webview.New(false)
	defer w.Destroy()
	C.installMenus() // menu nativo bilingue: App, File, Modifica, Vista, Finestra (con scorciatoie)
	// NB: nessuna richiesta permessi all'avvio. Vengono chiesti solo al primo uso del microfono
	// (gephidDictStart), e solo se l'utente ha abilitato la dettatura nelle Impostazioni.
	w.Bind("gephidDictStart", func(locale string) int { // avvia dettatura on-device nella lingua della UI
		cl := C.CString(locale)
		defer C.free(unsafe.Pointer(cl))
		return int(C.gephidDictStart(cl))
	})
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
	// DOPO SetSize: SetSize fa setFrame+center e sovrascriverebbe il frame ripristinato dall'autosave
	C.gephidSetupWindow(w.Window())
	w.SetHtml(page(tx("Carico Gephid…", "Loading Gephid…"),
		tx("Avvio il motore locale.", "Starting the local engine."), true))

	closed := make(chan struct{})
	done := make(chan struct{}) // chiuso quando la goroutine di supervisione è davvero terminata
	go func() {
		defer close(done)
		// FASE 1 — boot iniziale: aspetto che il backend risponda, poi navigo alla UI.
		deadline := time.Now().Add(120 * time.Second) // tetto basato su orologio reale
		booted := false
		for time.Now().Before(deadline) {
			select {
			case err := <-procDied: // morto durante il boot
				// Se la porta è già servita da un ALTRO backend (due finestre avviate nello stesso
				// istante: il mio ha perso la corsa al bind), adottalo invece di mostrare l'errore.
				if reachable, _, _ := checkHealth(); reachable {
					iStartedIt = false
					bmu.Lock()
					cmd = nil
					bmu.Unlock()
					procDied = nil // canale nil: in select non scatta più
					continue
				}
				msg := tx("Il backend Python si è chiuso inaspettatamente.", "The Python backend quit unexpectedly.")
				if err != nil {
					msg += "<br><br><code>" + html.EscapeString(err.Error()) + "</code>"
				}
				msg += "<br><br>" + tx("Controlla", "Check") + " <code>~/Library/Logs/Gephid/backend.log</code>."
				safeDispatch(w, closed, func() { w.SetHtml(page(tx("Backend terminato", "Backend stopped"), msg, false)) })
				return
			case <-closed:
				return
			default:
			}
			if reachable, _, _ := checkHealth(); reachable { // la UI è servita dal backend
				booted = true
				break
			}
			time.Sleep(1 * time.Second)
		}
		if !booted {
			safeDispatch(w, closed, func() {
				w.SetHtml(page(tx("Backend non pronto", "Backend not ready"),
					tx("Gephid non si è avviata entro 120s. Chiudi e riprova, o controlla i log.", "Gephid didn't start within 120s. Close and retry, or check the logs."), false))
			})
			return
		}
		safeDispatch(w, closed, func() { w.Navigate(backendURL) })
		go func() { // azioni dal menu nativo -> gephidMenu('x') nella pagina
			t := time.NewTicker(100 * time.Millisecond)
			defer t.Stop()
			for {
				select {
				case <-closed:
					return
				case <-t.C:
				}
				cs := C.gephidPopMenuAction()
				a := C.GoString(cs)
				C.free(unsafe.Pointer(cs))
				if a != "" && strings.Trim(a, "abcdefghijklmnopqrstuvwxyz") == "" { // solo nomi d'azione noti, mai input arbitrario
					safeDispatch(w, closed, func() { w.Eval("window.gephidMenu&&gephidMenu('" + a + "')") })
				}
			}
		}()

		// FASE 2 — supervisione: se il backend muore mentre la finestra è aperta, lo riavvio.
		// La pagina resta caricata e il suo heartbeat (/api/health) fa sparire da solo l'overlay
		// "Backend non raggiungibile" appena il backend torna su (e così "Ricarica" funziona di
		// nuovo). Non rinavigo: la chat in corso non va persa.
		if !iStartedIt {
			<-closed // backend di un'altra istanza: non lo gestisco io
			return
		}
		lastStart := time.Now()
		restarts := 0
		for {
			select {
			case <-closed:
				return
			case <-procDied: // backend morto
			}
			if time.Since(lastStart) > 60*time.Second {
				restarts = 0 // era stabile da un po': azzero il contatore dei tentativi
			}
			for { // riavvio con backoff progressivo (tetto 30s): mai arrendersi in silenzio —
				// l'overlay "Backend non raggiungibile" della pagina resta vero solo finché ritento
				select {
				case <-closed:
					return
				default:
				}
				restarts++
				wait := time.Duration(restarts) * time.Second
				if wait > 30*time.Second {
					wait = 30 * time.Second
				}
				select { // backoff progressivo, ma interrompibile dalla chiusura della finestra
				case <-closed:
					return
				case <-time.After(wait):
				}
				c, died, err := startBackend(py, script, home)
				if err == nil {
					bmu.Lock()
					cmd = c
					bmu.Unlock()
					procDied = died
					lastStart = time.Now()
					break
				}
				fmt.Println("Gephid: riavvio backend fallito:", err)
			}
		}
	}()

	w.Run() // blocca finché non chiudi la finestra
	close(closed)
	<-done // aspetto che la supervisione termini davvero: così cmd è stabile e non viene riavviato dopo il kill

	// Spegni il backend SOLO se sono l'ultima finestra Gephid: altrimenti orfanerei le altre.
	// Se restano altre finestre, lo lascio vivo (il launcher-watchdog del backend lo spegnerà
	// comunque quando davvero non resta nessun launcher).
	if otherLaunchersAlive() {
		fmt.Println("Gephid: altre finestre aperte, lascio il backend attivo.")
	} else {
		bmu.Lock()
		c := cmd
		bmu.Unlock()
		if c != nil {
			killBackend(c) // l'ho avviato io: spengo subito il mio gruppo di processi
			fmt.Println("Gephid: ultima finestra chiusa, backend spento.")
		} else {
			// backend riusato (avviato da un'altra istanza): NON lo killo per porta, ucciderei il
			// backend che una finestra appena aperta potrebbe aver adottato. Lo spegne il
			// launcher-watchdog del backend quando non resta nessun launcher.
			fmt.Println("Gephid: ultima finestra chiusa (backend riusato), lo lascio al watchdog.")
		}
	}
}

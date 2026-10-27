; ---------------------------------------------------------------------------
; Typra installer (NSIS 3.08+). Everything it does is in this file.
;
; Build:   installer\build.bat            (or: makensis installer\typra.nsi)
; Output:  installer\Typra_Setup_<version>.exe
;
; What Setup does, and nothing else:
;   * installs Typra for the current user in %LOCALAPPDATA%\Programs\Typra
;     (no administrator rights, no system-wide changes, PATH untouched);
;   * uses an existing 64-bit Python 3.11. Only if none is found, and only
;     after the user explicitly agrees, it downloads the official python.org
;     installer over HTTPS, verifies its SHA-256 and installs it per user;
;   * creates a virtual environment and installs the exact, SHA-256 pinned
;     wheels listed in requirements.lock (pip --require-hashes, no source builds);
;   * creates shortcuts that start pythonw.exe directly (no VBScript/batch).
; ---------------------------------------------------------------------------

Unicode true
ManifestDPIAware true
RequestExecutionLevel user
SetCompressor /SOLID lzma

!ifndef VERSION
  !define VERSION "2.1.0"
!endif

!define APPNAME     "Typra"
!define PUBLISHER   "Typra contributors"
!define HOMEPAGE    "https://github.com/BrisringDem93/Typra"
!define UNINST_KEY  "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"
!define APP_KEY     "Software\${APPNAME}"
; Must match _SINGLE_INSTANCE_MUTEX in main.py
!define MUTEX_NAME  "Local\Typra.OfflineDictation.SingleInstance"
!define SRC         ".."

; Official python.org installer, pinned by SHA-256
; (Authenticode signer: Python Software Foundation).
!define PY_VERSION  "3.11.9"
!define PY_URL      "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
!define PY_SHA256   "5ee42c4eee1e6b4464bb23722f90b45303f79442df63083f05322f1785f5fdde"
!define PY_TARGET   "$LOCALAPPDATA\Programs\Python\Python311"

Name "${APPNAME} ${VERSION}"
OutFile "Typra_Setup_${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
InstallDirRegKey HKCU "${APP_KEY}" "InstallDir"
BrandingText "${APPNAME} ${VERSION}"
ShowInstDetails show
ShowUninstDetails show

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "nsDialogs.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

Var PythonExe     ; usable python.exe, "" if none was found
Var PyConsent     ; 1 = the user agreed to install Python
Var PyCheckbox
Var Elevated      ; 1 = Setup was started as administrator anyway

; -- Pages --------------------------------------------------------------------

!define MUI_ICON   "${SRC}\typra.ico"
!define MUI_UNICON "${SRC}\typra.ico"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TEXT "$(WelcomeText)"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${SRC}\LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE DirectoryLeave
!insertmacro MUI_PAGE_DIRECTORY
Page custom PythonPageCreate PythonPageLeave
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TEXT "$(FinishText)"
!define MUI_FINISHPAGE_TEXT_LARGE
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "$(FinishRun)"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchTypra
!define MUI_PAGE_CUSTOMFUNCTION_SHOW FinishShow
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Italian"

VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=${LANG_ENGLISH} "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=${LANG_ENGLISH} "FileDescription" "${APPNAME} Setup"
VIAddVersionKey /LANG=${LANG_ENGLISH} "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=${LANG_ENGLISH} "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=${LANG_ENGLISH} "CompanyName" "${PUBLISHER}"
VIAddVersionKey /LANG=${LANG_ENGLISH} "LegalCopyright" "MIT License"

; -- Strings ------------------------------------------------------------------

LangString WelcomeText ${LANG_ENGLISH} "This wizard installs ${APPNAME} ${VERSION}, an offline dictation app, for the current user only. No administrator rights are needed.$\r$\n$\r$\nSetup uses your 64-bit Python 3.11 (or asks before installing it) and downloads the required Python packages from PyPI (about 200 MB), verifying each one with SHA-256.$\r$\n$\r$\nClick Next to continue."
LangString WelcomeText ${LANG_ITALIAN} "Questa procedura installa ${APPNAME} ${VERSION}, un'app di dettatura offline, solo per l'utente corrente. Non servono privilegi di amministratore.$\r$\n$\r$\nL'installazione usa il tuo Python 3.11 a 64 bit (o chiede il permesso prima di installarlo) e scarica da PyPI i pacchetti Python necessari (circa 200 MB), verificandoli uno per uno con SHA-256.$\r$\n$\r$\nFai clic su Avanti per continuare."

LangString SecCoreName ${LANG_ENGLISH} "Typra (required)"
LangString SecCoreName ${LANG_ITALIAN} "Typra (obbligatorio)"
LangString SecDesktopName ${LANG_ENGLISH} "Desktop shortcut"
LangString SecDesktopName ${LANG_ITALIAN} "Collegamento sul desktop"

LangString PyPageTitle ${LANG_ENGLISH} "Python 3.11 is required"
LangString PyPageTitle ${LANG_ITALIAN} "Serve Python 3.11"
LangString PyPageSubtitle ${LANG_ENGLISH} "Typra runs on Python, which was not found on this computer."
LangString PyPageSubtitle ${LANG_ITALIAN} "Typra funziona con Python, che non è stato trovato su questo computer."
LangString PyPageText ${LANG_ENGLISH} "Typra needs a 64-bit Python 3.11, and none was found on this computer.$\r$\n$\r$\nIf you agree, Setup downloads the official Python ${PY_VERSION} installer from www.python.org over HTTPS (about 25 MB), verifies its SHA-256 checksum and runs it only if the check passes. Python is installed for the current user only, without administrator rights and without changing PATH; you can remove it later from Settings > Apps.$\r$\n$\r$\nPrefer to do it yourself? Click Cancel, install Python 3.11 (64-bit) from python.org and run Setup again."
LangString PyPageText ${LANG_ITALIAN} "Typra richiede Python 3.11 a 64 bit, che non è stato trovato su questo computer.$\r$\n$\r$\nSe acconsenti, l'installazione scarica l'installer ufficiale di Python ${PY_VERSION} da www.python.org tramite HTTPS (circa 25 MB), ne verifica il checksum SHA-256 e lo esegue solo se la verifica riesce. Python viene installato solo per l'utente corrente, senza privilegi di amministratore e senza modificare il PATH; potrai rimuoverlo da Impostazioni > App.$\r$\n$\r$\nPreferisci farlo tu? Fai clic su Annulla, installa Python 3.11 (64 bit) da python.org ed esegui di nuovo l'installazione."
LangString PyPageSubtitleStore ${LANG_ENGLISH} "Your Python 3.11 is the Microsoft Store version, which Typra cannot use."
LangString PyPageSubtitleStore ${LANG_ITALIAN} "Il tuo Python 3.11 è la versione del Microsoft Store, che Typra non può usare."
LangString PyPageTextStore ${LANG_ENGLISH} "Python 3.11 from the Microsoft Store is installed, but Typra cannot use it: Store apps run in a sandbox that silently moves the files they write under AppData, so Typra's environment would end up in a hidden folder and stop working after Store updates.$\r$\n$\r$\nIf you agree, Setup installs the official Python ${PY_VERSION} from www.python.org next to it (HTTPS, about 25 MB, SHA-256 verified), for the current user only and without changing PATH. Your Store Python is not touched, and the two do not interfere."
LangString PyPageTextStore ${LANG_ITALIAN} "Python 3.11 del Microsoft Store è installato, ma Typra non può usarlo: le app dello Store girano in una sandbox che sposta di nascosto i file scritti in AppData, quindi l'ambiente di Typra finirebbe in una cartella nascosta e smetterebbe di funzionare dopo gli aggiornamenti dello Store.$\r$\n$\r$\nSe acconsenti, l'installazione aggiunge accanto il Python ${PY_VERSION} ufficiale da www.python.org (HTTPS, circa 25 MB, verificato con SHA-256), solo per l'utente corrente e senza modificare il PATH. Il Python dello Store non viene toccato e i due non interferiscono."
LangString PyPageCheckbox ${LANG_ENGLISH} "I agree: download and install Python ${PY_VERSION} (64-bit) from python.org"
LangString PyPageCheckbox ${LANG_ITALIAN} "Acconsento: scarica e installa Python ${PY_VERSION} (64 bit) da python.org"
LangString PyNoConsent ${LANG_ENGLISH} "Typra cannot be installed without Python 3.11.$\r$\n$\r$\nTick the box to let Setup install it, or click Cancel and install Python 3.11 (64-bit) from python.org yourself."
LangString PyNoConsent ${LANG_ITALIAN} "Typra non può essere installato senza Python 3.11.$\r$\n$\r$\nSeleziona la casella per farlo installare dal programma, oppure fai clic su Annulla e installa tu Python 3.11 (64 bit) da python.org."
LangString PyMissing ${LANG_ENGLISH} "Python 3.11 (64-bit) was not found. Install it from python.org, or run Setup with /INSTALLPYTHON to let Setup install it."
LangString PyMissing ${LANG_ITALIAN} "Python 3.11 (64 bit) non è stato trovato. Installalo da python.org, oppure esegui l'installazione con /INSTALLPYTHON per farlo installare automaticamente."
LangString PyNoCurl ${LANG_ENGLISH} "This version of Windows does not include curl.exe, which Setup uses to download Python securely.$\r$\n$\r$\nPlease install Python 3.11 (64-bit) from python.org yourself and run Setup again. The download page will open now."
LangString PyNoCurl ${LANG_ITALIAN} "Questa versione di Windows non include curl.exe, che serve per scaricare Python in modo sicuro.$\r$\n$\r$\nInstalla tu Python 3.11 (64 bit) da python.org ed esegui di nuovo l'installazione. Ora si aprirà la pagina di download."
LangString PyDownloadFailed ${LANG_ENGLISH} "Python could not be downloaded. Check your internet connection and try again."
LangString PyDownloadFailed ${LANG_ITALIAN} "Impossibile scaricare Python. Controlla la connessione a Internet e riprova."
LangString PyHashMismatch ${LANG_ENGLISH} "The downloaded Python installer failed the SHA-256 integrity check, so it was deleted without being run.$\r$\n$\r$\nThe download may be corrupted, or your connection may have been tampered with."
LangString PyHashMismatch ${LANG_ITALIAN} "L'installer di Python scaricato non ha superato il controllo di integrità SHA-256, quindi è stato eliminato senza essere eseguito.$\r$\n$\r$\nIl download potrebbe essere danneggiato oppure la connessione potrebbe essere stata manomessa."
LangString PyInstallFailed ${LANG_ENGLISH} "The Python installation did not complete (exit code $0)."
LangString PyInstallFailed ${LANG_ITALIAN} "L'installazione di Python non è stata completata (codice di uscita $0)."
LangString PyNotFoundAfterInstall ${LANG_ENGLISH} "Python was installed but could not be found. Please run Setup again."
LangString PyNotFoundAfterInstall ${LANG_ITALIAN} "Python è stato installato ma non è stato trovato. Esegui di nuovo l'installazione."

LangString DetailUsingPython ${LANG_ENGLISH} "Using Python:"
LangString DetailUsingPython ${LANG_ITALIAN} "Python in uso:"
LangString DetailDownloadingPython ${LANG_ENGLISH} "Downloading Python ${PY_VERSION} from python.org..."
LangString DetailDownloadingPython ${LANG_ITALIAN} "Download di Python ${PY_VERSION} da python.org..."
LangString DetailVerifyingPython ${LANG_ENGLISH} "Verifying the SHA-256 checksum..."
LangString DetailVerifyingPython ${LANG_ITALIAN} "Verifica del checksum SHA-256..."
LangString DetailInstallingPython ${LANG_ENGLISH} "Installing Python ${PY_VERSION} for the current user..."
LangString DetailInstallingPython ${LANG_ITALIAN} "Installazione di Python ${PY_VERSION} per l'utente corrente..."
LangString DetailCreatingVenv ${LANG_ENGLISH} "Creating the virtual environment..."
LangString DetailCreatingVenv ${LANG_ITALIAN} "Creazione dell'ambiente virtuale..."
LangString DetailInstallingPackages ${LANG_ENGLISH} "Installing the Python packages (this can take a few minutes)..."
LangString DetailInstallingPackages ${LANG_ITALIAN} "Installazione dei pacchetti Python (può richiedere qualche minuto)..."

LangString VenvFailed ${LANG_ENGLISH} "The Python virtual environment could not be created."
LangString VenvFailed ${LANG_ITALIAN} "Impossibile creare l'ambiente virtuale Python."
LangString PipFailed ${LANG_ENGLISH} "Installing the Python packages failed. Check your internet connection and run Setup again. An existing installation was left unchanged.$\r$\n$\r$\nThe log is shown in the Setup window (right-click it > Copy Details To Clipboard)."
LangString PipFailed ${LANG_ITALIAN} "L'installazione dei pacchetti Python non è riuscita. Controlla la connessione a Internet ed esegui di nuovo l'installazione. Un'eventuale installazione precedente non è stata modificata.$\r$\n$\r$\nIl log è nella finestra dell'installazione (clic destro > Copy Details To Clipboard)."
LangString SwapFailed ${LANG_ENGLISH} "The previous Python environment could not be replaced (is Typra still running?). Quit Typra and run Setup again."
LangString SwapFailed ${LANG_ITALIAN} "Non è stato possibile sostituire il precedente ambiente Python (Typra è ancora in esecuzione?). Chiudi Typra ed esegui di nuovo l'installazione."
LangString PyStartFailed ${LANG_ENGLISH} "The Python installer could not be started (it may have been blocked by a policy or by your antivirus)."
LangString PyStartFailed ${LANG_ITALIAN} "Non è stato possibile avviare l'installer di Python (potrebbe essere stato bloccato da un criterio o dall'antivirus)."
LangString RunningElevated ${LANG_ENGLISH} "Setup is running as administrator, which it does not need. Typra would be installed for the administrator account and would not be started at the end.$\r$\n$\r$\nTo install it for your own account, click Cancel and run Setup normally."
LangString RunningElevated ${LANG_ITALIAN} "L'installazione è in esecuzione come amministratore, cosa che non serve. Typra verrebbe installato per l'account amministratore e non verrebbe avviato alla fine.$\r$\n$\r$\nPer installarlo nel tuo account, fai clic su Annulla ed esegui l'installazione normalmente."
LangString DetailGpu ${LANG_ENGLISH} "Reinstalling GPU support (NVIDIA cuBLAS, about 630 MB)..."
LangString DetailGpu ${LANG_ITALIAN} "Reinstallazione del supporto GPU (NVIDIA cuBLAS, circa 630 MB)..."
LangString GpuNotKept ${LANG_ENGLISH} "GPU support could not be reinstalled, so Typra will use the CPU for now. Install it again from Settings > Advanced > Install GPU support."
LangString GpuNotKept ${LANG_ITALIAN} "Non è stato possibile reinstallare il supporto GPU, quindi per ora Typra userà la CPU. Reinstallalo da Impostazioni > Advanced > Install GPU support."
LangString LlamaRemoved ${LANG_ENGLISH} "The optional llama-cpp-python package (AI Cleanup) is not part of the new installation. If you use AI Cleanup, install it again as described in the README."
LangString LlamaRemoved ${LANG_ITALIAN} "Il pacchetto opzionale llama-cpp-python (AI Cleanup) non fa parte della nuova installazione. Se usi AI Cleanup, installalo di nuovo come descritto nel README."
LangString DirNotEmpty ${LANG_ENGLISH} "The selected folder is not empty and does not contain a previous Typra installation.$\r$\n$\r$\nPlease choose an empty or new folder."
LangString DirNotEmpty ${LANG_ITALIAN} "La cartella selezionata non è vuota e non contiene una precedente installazione di Typra.$\r$\n$\r$\nScegli una cartella vuota o nuova."
LangString TypraRunning ${LANG_ENGLISH} "Typra is running.$\r$\n$\r$\nQuit it from the tray icon (right-click > Quit Typra), then click Retry."
LangString TypraRunning ${LANG_ITALIAN} "Typra è in esecuzione.$\r$\n$\r$\nChiudilo dall'icona nell'area di notifica (clic destro > Quit Typra), poi fai clic su Riprova."
LangString UnsupportedOS ${LANG_ENGLISH} "Typra requires 64-bit Windows 10 or later."
LangString UnsupportedOS ${LANG_ITALIAN} "Typra richiede Windows 10 o successivo a 64 bit."
LangString OldInstallFound ${LANG_ENGLISH} "An older Typra installation for all users was found.$\r$\n$\r$\nIt is recommended to remove it from Settings > Apps before continuing. Note: its uninstaller force-closes every running pythonw.exe program, so save your work in other Python programs first.$\r$\n$\r$\nContinue anyway?"
LangString OldInstallFound ${LANG_ITALIAN} "È stata trovata una vecchia installazione di Typra per tutti gli utenti.$\r$\n$\r$\nTi consigliamo di rimuoverla da Impostazioni > App prima di continuare. Nota: il suo programma di disinstallazione chiude forzatamente tutti i programmi pythonw.exe in esecuzione, quindi salva prima il lavoro negli altri programmi Python.$\r$\n$\r$\nContinuare comunque?"

LangString FinishText ${LANG_ENGLISH} "Typra has been installed. Its icon appears in the system tray; press Ctrl+Shift+Space to start and stop dictation.$\r$\nOn first launch the speech model (about 145 MB) is downloaded from Hugging Face."
LangString FinishText ${LANG_ITALIAN} "Typra è stato installato. L'icona compare nell'area di notifica; premi Ctrl+Maiusc+Spazio per avviare e fermare la dettatura.$\r$\nAl primo avvio il modello vocale (circa 145 MB) viene scaricato da Hugging Face."
LangString FinishRun ${LANG_ENGLISH} "Start Typra now"
LangString FinishRun ${LANG_ITALIAN} "Avvia Typra ora"

LangString UnNotTypraDir ${LANG_ENGLISH} "$INSTDIR does not look like a Typra installation, so nothing was removed."
LangString UnNotTypraDir ${LANG_ITALIAN} "$INSTDIR non sembra un'installazione di Typra, quindi non è stato rimosso nulla."
LangString UnDeleteData ${LANG_ENGLISH} "Do you also want to permanently delete your Typra data?$\r$\n$\r$\nThis includes your dictation history, settings, log file and the downloaded speech and AI models in:$\r$\n$PROFILE\.whisper_dictation$\r$\n$\r$\nChoose No to keep them."
LangString UnDeleteData ${LANG_ITALIAN} "Vuoi eliminare definitivamente anche i tuoi dati di Typra?$\r$\n$\r$\nComprendono lo storico delle dettature, le impostazioni, il file di log e i modelli vocali e AI scaricati in:$\r$\n$PROFILE\.whisper_dictation$\r$\n$\r$\nScegli No per conservarli."
LangString UnPythonInfo ${LANG_ENGLISH} "Python ${PY_VERSION} was installed by Typra Setup and has not been removed, because other programs may use it.$\r$\n$\r$\nYou can uninstall it from Settings > Apps if you no longer need it."
LangString UnPythonInfo ${LANG_ITALIAN} "Python ${PY_VERSION} è stato installato da Typra e non è stato rimosso, perché altri programmi potrebbero usarlo.$\r$\n$\r$\nPuoi disinstallarlo da Impostazioni > App se non ti serve più."

; -- Shared helpers (installer and uninstaller) ------------------------------

; Typra holds a named mutex while it runs (see main.py).
!macro CHECK_TYPRA_NOT_RUNNING_FUNC UN
Function ${UN}CheckTypraNotRunning
  retry:
    System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "${MUTEX_NAME}") i .r0 ?e'
    Pop $1   ; last error: 5 (access denied) = held by a Typra running as admin
    ${If} $0 == 0
    ${AndIf} $1 != 5
      Return
    ${EndIf}
    ${If} $0 != 0
      System::Call 'kernel32::CloseHandle(i r0)'
    ${EndIf}
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(TypraRunning)" /SD IDCANCEL IDRETRY retry
    Quit
FunctionEnd
!macroend
!insertmacro CHECK_TYPRA_NOT_RUNNING_FUNC ""
!insertmacro CHECK_TYPRA_NOT_RUNNING_FUNC "un."

!macro REMOVE_PACKAGE NAME
  Delete "$INSTDIR\${NAME}\*.py"
  RMDir /r "$INSTDIR\${NAME}\__pycache__"
  RMDir "$INSTDIR\${NAME}"
!macroend

; Removes only the files Setup installs (upgrades must not leave stale modules).
!macro REMOVE_APP_CODE_FUNC UN
Function ${UN}RemoveAppCode
  Delete "$INSTDIR\main.py"
  Delete "$INSTDIR\download_models.py"
  Delete "$INSTDIR\requirements.txt"
  Delete "$INSTDIR\requirements.lock"
  Delete "$INSTDIR\requirements-gpu.txt"
  Delete "$INSTDIR\requirements-gpu.lock"
  Delete "$INSTDIR\setup.bat"
  Delete "$INSTDIR\run.bat"
  Delete "$INSTDIR\typra.ico"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\assets\*.ico"
  Delete "$INSTDIR\assets\*.svg"
  RMDir "$INSTDIR\assets"
  !insertmacro REMOVE_PACKAGE audio
  !insertmacro REMOVE_PACKAGE config
  !insertmacro REMOVE_PACKAGE db
  !insertmacro REMOVE_PACKAGE input
  !insertmacro REMOVE_PACKAGE stt
  !insertmacro REMOVE_PACKAGE ui
FunctionEnd
!macroend
!insertmacro REMOVE_APP_CODE_FUNC ""
!insertmacro REMOVE_APP_CODE_FUNC "un."

; -- Installer helpers --------------------------------------------------------

; $R0 = 1 if $R1 occurs in $R2 (case-insensitive), else 0.
Function StrContains
  Push $R3
  Push $R4
  Push $R5
  StrLen $R3 $R1
  StrCpy $R4 0
  StrCpy $R0 0
  loop:
    StrCpy $R5 $R2 $R3 $R4
    StrCmp $R5 "" done
    StrCmp $R5 $R1 found
    IntOp $R4 $R4 + 1
    Goto loop
  found:
    StrCpy $R0 1
  done:
  Pop $R5
  Pop $R4
  Pop $R3
FunctionEnd

; $R0 = 1 if $INSTDIR is new, empty, or an existing Typra installation.
; Setup and its uninstaller delete .venv and code folders inside $INSTDIR,
; so they must never be pointed at a folder holding someone else's files.
Function IsSafeInstallDir
  StrCpy $R0 1
  ${If} ${FileExists} "$INSTDIR\main.py"
  ${AndIf} ${FileExists} "$INSTDIR\stt\transcriber.py"
    Return
  ${EndIf}
  ClearErrors
  FindFirst $0 $1 "$INSTDIR\*.*"
  ${DoWhile} $1 != ""
    ${If} $1 != "."
    ${AndIf} $1 != ".."
      StrCpy $R0 0
      ${Break}
    ${EndIf}
    FindNext $0 $1
  ${Loop}
  FindClose $0
FunctionEnd

; $0 = candidate python.exe. Sets $PythonExe if it is a 64-bit CPython 3.11.
Function TryPython
  ${If} $0 == ""
    Return
  ${EndIf}
  ${IfNot} ${FileExists} "$0"
    Return
  ${EndIf}
  ; Skip Microsoft Store builds: their registered path is an access-restricted
  ; WindowsApps folder named after the version, which every Store update replaces.
  StrCpy $R1 "\WindowsApps\"
  StrCpy $R2 "$0"
  Call StrContains
  ${If} $R0 == 1
    Return
  ${EndIf}
  nsExec::ExecToStack `"$0" -I -c "import sys, struct; sys.exit(0 if sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8 else 1)"`
  Pop $1
  Pop $2
  ${If} $1 == 0
    StrCpy $PythonExe "$0"
  ${EndIf}
FunctionEnd

; Sets $PythonExe to a usable Python 3.11 (python.org default locations first,
; then the PEP 514 registrations), or "" if there is none.
Function FindPython
  StrCpy $PythonExe ""
  StrCpy $0 "${PY_TARGET}\python.exe"
  Call TryPython
  ${If} $PythonExe == ""
    StrCpy $0 "$PROGRAMFILES64\Python311\python.exe"
    Call TryPython
  ${EndIf}
  SetRegView 64
  ${If} $PythonExe == ""
    ReadRegStr $0 HKCU "Software\Python\PythonCore\3.11\InstallPath" "ExecutablePath"
    Call TryPython
  ${EndIf}
  ${If} $PythonExe == ""
    ReadRegStr $0 HKLM "Software\Python\PythonCore\3.11\InstallPath" "ExecutablePath"
    Call TryPython
  ${EndIf}
  SetRegView default
FunctionEnd

; Downloads python.org's installer over HTTPS, verifies it, installs it per user.
Function InstallPython
  InitPluginsDir
  StrCpy $3 "$PLUGINSDIR\python-${PY_VERSION}-amd64.exe"

  ; Windows 10 1803+ ships curl.exe, which uses the Windows certificate store.
  ${IfNot} ${FileExists} "$SYSDIR\curl.exe"
    MessageBox MB_ICONSTOP "$(PyNoCurl)" /SD IDOK
    ExecShell "open" "https://www.python.org/downloads/release/python-3119/"
    SetErrorLevel 2
    Abort
  ${EndIf}

  ; curl ignores the proxy set in Windows settings: pass a simple one explicitly
  StrCpy $4 ""
  ReadRegDWORD $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Internet Settings" "ProxyEnable"
  ReadRegStr $1 HKCU "Software\Microsoft\Windows\CurrentVersion\Internet Settings" "ProxyServer"
  ${If} $0 == 1
  ${AndIf} $1 != ""
    StrCpy $R1 "="
    StrCpy $R2 $1
    Call StrContains
    ${If} $R0 == 0
      StrCpy $4 '--proxy "$1"'
    ${EndIf}
  ${EndIf}

  DetailPrint "$(DetailDownloadingPython)"
  nsExec::ExecToLog '"$SYSDIR\curl.exe" $4 --fail --location --proto =https --proto-redir =https --tlsv1.2 --retry 3 --silent --show-error --output "$3" "${PY_URL}"'
  Pop $0
  ${If} $0 != 0
    ; Behind HTTPS inspection the certificate revocation list is often
    ; unreachable. The SHA-256 check below protects the file either way.
    nsExec::ExecToLog '"$SYSDIR\curl.exe" $4 --ssl-revoke-best-effort --fail --location --proto =https --proto-redir =https --tlsv1.2 --retry 3 --silent --show-error --output "$3" "${PY_URL}"'
    Pop $0
  ${EndIf}
  ${If} $0 != 0
    Delete "$3"
    MessageBox MB_ICONSTOP "$(PyDownloadFailed)" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}

  DetailPrint "$(DetailVerifyingPython)"
  nsExec::ExecToStack '"$SYSDIR\certutil.exe" -hashfile "$3" SHA256'
  Pop $0
  Pop $2
  StrCpy $R1 "${PY_SHA256}"
  StrCpy $R2 $2
  Call StrContains
  ${If} $0 != 0
  ${OrIf} $R0 != 1
    Delete "$3"
    MessageBox MB_ICONSTOP "$(PyHashMismatch)" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}

  DetailPrint "$(DetailInstallingPython)"
  StrCpy $0 "error"
  ClearErrors
  ExecWait '"$3" /passive InstallAllUsers=0 TargetDir="${PY_TARGET}" PrependPath=0 Include_launcher=0 InstallLauncherAllUsers=0 Include_test=0 Include_doc=0 Include_tcltk=0 Shortcuts=0 AssociateFiles=0 Include_pip=1' $0
  ${If} ${Errors}
    Delete "$3"
    MessageBox MB_ICONSTOP "$(PyStartFailed)" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  Delete "$3"
  ${If} $0 != 0
  ${AndIf} $0 != 3010
    MessageBox MB_ICONSTOP "$(PyInstallFailed)" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}

  Call FindPython
  ${If} $PythonExe == ""
    MessageBox MB_ICONSTOP "$(PyNotFoundAfterInstall)" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  WriteRegDWORD HKCU "${APP_KEY}" "PythonInstalledByTypra" 1
FunctionEnd

; -- Installer callbacks ------------------------------------------------------

Function .onInit
  ${IfNot} ${RunningX64}
  ${OrIfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP "$(UnsupportedOS)" /SD IDOK
    Abort
  ${EndIf}

  ; Unattended installs may pre-approve the Python download: /INSTALLPYTHON
  ${GetParameters} $R0
  ClearErrors
  ${GetOptions} $R0 "/INSTALLPYTHON" $R1
  ${IfNot} ${Errors}
    StrCpy $PyConsent 1
  ${EndIf}

  Call CheckTypraNotRunning

  ; "Run as administrator" would install into the admin profile and start
  ; Typra elevated; it is not needed.
  System::Call 'shell32::IsUserAnAdmin() i .r0'
  ${If} $0 != 0
    StrCpy $Elevated 1
    MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION|MB_DEFBUTTON2 "$(RunningElevated)" /SD IDOK IDOK elevated_ok
    Abort
    elevated_ok:
  ${EndIf}

  ; The original v1/v2 installers installed for all users (32-bit registry view).
  ReadRegStr $0 HKLM "${UNINST_KEY}" "UninstallString"
  ${If} $0 != ""
    MessageBox MB_OKCANCEL|MB_ICONINFORMATION "$(OldInstallFound)" /SD IDOK IDOK old_install_ok
    Abort
    old_install_ok:
  ${EndIf}
FunctionEnd

Function DirectoryLeave
  Call IsSafeInstallDir
  ${If} $R0 != 1
    MessageBox MB_ICONEXCLAMATION "$(DirNotEmpty)"
    Abort
  ${EndIf}
FunctionEnd

Function PythonPageCreate
  Call FindPython
  ${If} $PythonExe != ""
    Abort   ; Python 3.11 is already installed: skip this page
  ${EndIf}

  ; A Microsoft Store Python 3.11 is skipped by FindPython: say so instead of "not found"
  StrCpy $1 0
  ${If} ${FileExists} "$LOCALAPPDATA\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\python.exe"
    StrCpy $1 1
  ${EndIf}
  ${If} $1 == 1
    !insertmacro MUI_HEADER_TEXT "$(PyPageTitle)" "$(PyPageSubtitleStore)"
  ${Else}
    !insertmacro MUI_HEADER_TEXT "$(PyPageTitle)" "$(PyPageSubtitle)"
  ${EndIf}
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${If} $1 == 1
    ${NSD_CreateLabel} 0 0 100% 112u "$(PyPageTextStore)"
  ${Else}
    ${NSD_CreateLabel} 0 0 100% 112u "$(PyPageText)"
  ${EndIf}
  Pop $0
  ${NSD_CreateCheckBox} 0 118u 100% 18u "$(PyPageCheckbox)"
  Pop $PyCheckbox
  ${If} $PyConsent == 1
    ${NSD_Check} $PyCheckbox
  ${EndIf}
  nsDialogs::Show
FunctionEnd

Function PythonPageLeave
  ${NSD_GetState} $PyCheckbox $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $PyConsent 1
  ${Else}
    StrCpy $PyConsent 0
    MessageBox MB_ICONEXCLAMATION "$(PyNoConsent)"
    Abort
  ${EndIf}
FunctionEnd

Function FinishShow
  ; Never start Typra from an elevated Setup: it would run as administrator
  ${If} $Elevated == 1
    ${NSD_Uncheck} $mui.FinishPage.Run
    ShowWindow $mui.FinishPage.Run ${SW_HIDE}
  ${EndIf}
FunctionEnd

Function LaunchTypra
  ${If} $Elevated == 1
    Return
  ${EndIf}
  SetOutPath "$INSTDIR"
  ; -E: ignore PYTHONPATH/PYTHONHOME set for other Python programs
  Exec '"$INSTDIR\.venv\Scripts\pythonw.exe" -E "$INSTDIR\main.py"'
FunctionEnd

; -- Sections -----------------------------------------------------------------

!macro INSTALL_PACKAGE NAME
  SetOutPath "$INSTDIR\${NAME}"
  File "${SRC}\${NAME}\*.py"
!macroend

Section "$(SecCoreName)" SecCore
  SectionIn RO
  AddSize 750000   ; KB, mostly the virtual environment

  ; Silent installs skip the directory page, so check here as well.
  Call IsSafeInstallDir
  ${If} $R0 != 1
    MessageBox MB_ICONSTOP "$(DirNotEmpty)" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  ; Typra may have been started since Setup opened
  Call CheckTypraNotRunning

  ; 1. Python 3.11: reuse it if present, install it only with consent
  ${If} $PythonExe == ""
    Call FindPython
  ${EndIf}
  ${If} $PythonExe == ""
    ${If} $PyConsent != 1
      MessageBox MB_ICONSTOP "$(PyMissing)" /SD IDOK
      SetErrorLevel 2
      Abort
    ${EndIf}
    Call InstallPython
  ${EndIf}
  DetailPrint "$(DetailUsingPython) $PythonExe"

  ; 2. New virtual environment with the exact, hash-pinned wheels, built next
  ;    to the current one: an upgrade that fails here leaves the working
  ;    installation untouched. (-I: ignore PYTHONPATH/PYTHONHOME)
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File "${SRC}\requirements.lock"
  File "${SRC}\requirements-gpu.lock"
  SetOutPath "$INSTDIR"
  StrCpy $5 0
  StrCpy $6 0
  StrCpy $7 0
  ${If} ${FileExists} "$INSTDIR\.venv\Lib\site-packages\nvidia\cublas\bin\cublas64_12.dll"
    StrCpy $6 1   ; GPU support installed from Settings: keep it
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\.venv\Lib\site-packages\llama_cpp\*.*"
    StrCpy $5 1   ; optional AI Cleanup package, installed by hand
  ${EndIf}
  DetailPrint "$(DetailCreatingVenv)"
  RMDir /r "$INSTDIR\.venv.new"
  nsExec::ExecToLog '"$PythonExe" -I -m venv "$INSTDIR\.venv.new"'
  Pop $0
  ${If} $0 != 0
    RMDir /r "$INSTDIR\.venv.new"
    RMDir "$INSTDIR"
    MessageBox MB_ICONSTOP "$(VenvFailed)" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}

  DetailPrint "$(DetailInstallingPackages)"
  ; truststore = use the Windows certificate store, so pip also works behind
  ; antivirus or corporate HTTPS inspection
  nsExec::ExecToLog '"$INSTDIR\.venv.new\Scripts\python.exe" -I -m pip install --use-feature=truststore --disable-pip-version-check --no-input --require-hashes --only-binary=:all: -r "$PLUGINSDIR\requirements.lock"'
  Pop $0
  ${If} $0 != 0
    ; pip before 22.2 does not know the feature, and pip before 24.0 needs
    ; truststore installed separately: retry with pip's own certificates
    nsExec::ExecToLog '"$INSTDIR\.venv.new\Scripts\python.exe" -I -m pip install --disable-pip-version-check --no-input --require-hashes --only-binary=:all: -r "$PLUGINSDIR\requirements.lock"'
    Pop $0
  ${EndIf}
  ${If} $0 != 0
    RMDir /r "$INSTDIR\.venv.new"
    RMDir "$INSTDIR"
    MessageBox MB_ICONSTOP "$(PipFailed)" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  ; GPU support is optional: if it cannot be reinstalled, Typra uses the CPU
  ${If} $6 == 1
    DetailPrint "$(DetailGpu)"
    nsExec::ExecToLog '"$INSTDIR\.venv.new\Scripts\python.exe" -I -m pip install --use-feature=truststore --disable-pip-version-check --no-input --require-hashes --only-binary=:all: -r "$PLUGINSDIR\requirements-gpu.lock"'
    Pop $0
    ${If} $0 != 0
      nsExec::ExecToLog '"$INSTDIR\.venv.new\Scripts\python.exe" -I -m pip install --disable-pip-version-check --no-input --require-hashes --only-binary=:all: -r "$PLUGINSDIR\requirements-gpu.lock"'
      Pop $0
    ${EndIf}
    ${If} $0 != 0
      StrCpy $7 1
    ${EndIf}
  ${EndIf}

  ; 3. Application files
  SetOutPath "$INSTDIR"
  Call RemoveAppCode
  File "${SRC}\main.py"
  File "${SRC}\download_models.py"
  File "${SRC}\requirements.txt"
  File "${SRC}\requirements.lock"
  File "${SRC}\requirements-gpu.txt"
  File "${SRC}\requirements-gpu.lock"
  File "${SRC}\setup.bat"
  File "${SRC}\run.bat"
  File "${SRC}\typra.ico"
  File "${SRC}\README.md"
  File "${SRC}\LICENSE"
  SetOutPath "$INSTDIR\assets"
  File "${SRC}\assets\*.ico"
  File "${SRC}\assets\*.svg"
  !insertmacro INSTALL_PACKAGE audio
  !insertmacro INSTALL_PACKAGE config
  !insertmacro INSTALL_PACKAGE db
  !insertmacro INSTALL_PACKAGE input
  !insertmacro INSTALL_PACKAGE stt
  !insertmacro INSTALL_PACKAGE ui

  ; 4. Swap in the new environment
  RMDir /r "$INSTDIR\.venv"
  ClearErrors
  Rename "$INSTDIR\.venv.new" "$INSTDIR\.venv"
  ${If} ${Errors}
    MessageBox MB_ICONSTOP "$(SwapFailed)" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}

  ; 5. Uninstaller and Apps & Features entry
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${APP_KEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "URLInfoAbout" "${HOMEPAGE}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\typra.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

  ; 6. Start menu shortcut: pythonw.exe directly, working folder = $INSTDIR
  SetOutPath "$INSTDIR"
  CreateShortcut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\.venv\Scripts\pythonw.exe" '-E "$INSTDIR\main.py"' "$INSTDIR\typra.ico" 0
  ${If} $5 == 1
    MessageBox MB_ICONINFORMATION "$(LlamaRemoved)" /SD IDOK
  ${EndIf}
  ${If} $7 == 1
    MessageBox MB_ICONEXCLAMATION "$(GpuNotKept)" /SD IDOK
  ${EndIf}

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Section "$(SecDesktopName)" SecDesktop
  SetOutPath "$INSTDIR"
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\.venv\Scripts\pythonw.exe" '-E "$INSTDIR\main.py"' "$INSTDIR\typra.ico" 0
SectionEnd

; -- Uninstaller --------------------------------------------------------------

Function un.onInit
  Call un.CheckTypraNotRunning
FunctionEnd

Section "Uninstall"
  ; Typra may have been started since the uninstaller opened
  Call un.CheckTypraNotRunning
  ${IfNot} ${FileExists} "$INSTDIR\main.py"
  ${OrIfNot} ${FileExists} "$INSTDIR\stt\transcriber.py"
    MessageBox MB_ICONSTOP "$(UnNotTypraDir)" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}

  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  Delete "$DESKTOP\${APPNAME}.lnk"

  RMDir /r "$INSTDIR\.venv"
  Call un.RemoveAppCode
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"

  ; User data stays unless the user explicitly asks to delete it.
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "$(UnDeleteData)" /SD IDNO IDNO keep_data
    RMDir /r "$PROFILE\.whisper_dictation"
  keep_data:

  ReadRegDWORD $0 HKCU "${APP_KEY}" "PythonInstalledByTypra"
  ${If} $0 == 1
    MessageBox MB_ICONINFORMATION "$(UnPythonInfo)" /SD IDOK
  ${EndIf}

  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "${APP_KEY}"
SectionEnd

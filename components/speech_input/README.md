# Browser Speech Input Boundary

This folder is the future Streamlit component boundary for speech-to-text.

The planned flow is deliberately narrow:

1. The customer taps a microphone control in the browser.
2. Browser Speech API recognition runs with `ar-AE` for Arabic cases or `en-US`
   for English cases.
3. The transcript is written into the same customer message box.
4. The backend still runs `detect_language -> run_case -> localized reply`.

Speech is only an input method. Policy, fraud scoring, triage, human approval,
and customer notice generation remain server-side and deterministic.

// R-201-204: pure helpers for the PromptBar mic — extracted so the
// non-trivial bits of the ramble→transcribe→propose flow are unit-testable
// without a DOM/MediaRecorder harness (PromptBar.tsx itself has no test
// infra; see frontend/src/lib/moduleSaver.ts for the same pattern).

// Preferred MediaRecorder mime types, most-specific first. Injected as a
// predicate (rather than calling MediaRecorder.isTypeSupported directly) so
// this stays pure and testable without a browser.
const PREFERRED_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm"];

/**
 * Picks the best-supported MediaRecorder mime type for a ramble recording.
 * Prefers webm/opus, falls back to plain webm. If the browser supports
 * neither (e.g. Safari), returns undefined so the caller constructs a bare
 * `new MediaRecorder(stream)` and lets the browser pick its own default —
 * never throws for an unsupported explicit type.
 */
export function pickAudioMime(isSupported: (mimeType: string) => boolean): string | undefined {
  return PREFERRED_MIME_TYPES.find((type) => {
    try {
      return isSupported(type);
    } catch {
      return false;
    }
  });
}

/**
 * R-201: a transcript is APPENDED to whatever is already in the input, never
 * overwrites it. Space-joins the two non-empty pieces; trims stray edge
 * whitespace from each side without touching interior spacing.
 */
export function appendTranscript(existing: string, transcript: string): string {
  const left = existing.trim();
  const right = transcript.trim();
  if (!left) return right;
  if (!right) return left;
  return `${left} ${right}`;
}

/** mm:ss elapsed-time label for the recording indicator. */
export function formatElapsed(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

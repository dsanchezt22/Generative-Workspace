"use client";

// R-201-204: the ramble recorder, lifted out of PromptBar so both the prompt
// bar and the entry-screen front door (R-101) drive the SAME record → transcribe
// → deliver flow. The hook owns all the stateful browser plumbing (MediaRecorder,
// Web Speech garnish, feature detection, timers, cleanup); the caller decides
// what to do with the finished transcript via `onTranscript` (append + maybe
// auto-submit). Pure helpers live in ./voiceRamble (unit-tested there); this
// file is orchestration only — no test infra, verified by manual trace + tsc.

import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { pickAudioMime } from "@/lib/voiceRamble";

const noop = () => {};

// R-201 (fix): the Web-Speech FALLBACK (server STT unconfigured → 422) is
// delivered from the browser recognizer, which routinely stops after ~60s / on
// silence — so a long ramble can be truncated. Flag it so the user knows to
// review before submitting.
const WEB_SPEECH_FALLBACK_NOTICE =
  "Built from browser speech recognition — may be incomplete.";

export type VoiceMode = "none" | "speech-only" | "full";

export interface UseVoiceRambleOptions {
  // Current input text — read at record-start to decide auto-submit (R-202).
  getInput: () => string;
  // The AUTHORITATIVE transcript (server, or Web Speech fallback on 422) plus
  // whether the input was empty when recording started. The caller appends it
  // (never overwrites) and auto-submits when it was empty.
  onTranscript: (text: string, wasEmptyAtStart: boolean) => void;
  // Surface an error, or clear it (null) when a fresh recording starts.
  onError: (message: string | null) => void;
}

export interface VoiceRamble {
  voiceMode: VoiceMode;
  recording: boolean;
  transcribing: boolean;
  elapsedSec: number;
  liveInterim: string;
  toggleMic: () => void;
}

export function useVoiceRamble(options: UseVoiceRambleOptions): VoiceRamble {
  const [recording, setRecording] = useState(false);
  // R-201: true while the stopped recording's blob is in flight to
  // /api/transcribe — recording has ended but there's no transcript yet.
  const [transcribing, setTranscribing] = useState(false);
  const [elapsedSec, setElapsedSec] = useState(0);
  // Web Speech interim text shown as a ghosted live preview WHILE recording —
  // visual only; the server transcript is authoritative (see finishFullRecording).
  const [liveInterim, setLiveInterim] = useState("");
  // Feature-detected once on mount (client-only): "full" = MediaRecorder +
  // getUserMedia; "speech-only" = old iOS Safari etc. without MediaRecorder;
  // "none" = neither, so the caller hides the mic button (R-204).
  const [voiceMode, setVoiceMode] = useState<VoiceMode>("none");

  // Always-fresh callbacks: a recording can span re-renders, and the recorder's
  // onstop closes over the start-time render — reading through this ref delivers
  // to the latest handlers rather than a stale closure. Updated after each commit
  // (voice events only fire async, so the post-commit window is never observed).
  const cbRef = useRef(options);
  useEffect(() => { cbRef.current = options; });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recRef = useRef<any>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  // Was the input empty when THIS recording started — decides auto-submit (R-202).
  const wasEmptyAtStartRef = useRef(false);
  // Set on unmount so a recording torn down mid-flight (skip / re-entry while the
  // mic is hot) skips the now-pointless transcribe network call.
  const unmountedRef = useRef(false);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Accumulated Web Speech FINAL transcript during a "full" recording — used
  // only as a fallback if the server transcript comes back 422 (STT unconfigured).
  const speechFinalRef = useRef("");

  // Feature-detect once on mount (window/navigator absent during SSR).
  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const hasRecorder = typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
    setVoiceMode(hasRecorder ? "full" : SR ? "speech-only" : "none");
  }, []);

  // Never leave the mic "hot" if the caller unmounts mid-recording. .stop()
  // throws InvalidStateError on an "inactive" recorder, so it MUST be guarded.
  useEffect(() => {
    return () => {
      unmountedRef.current = true;
      if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
      const mr = mediaRecorderRef.current;
      if (mr && mr.state !== "inactive") mr.stop(); // → onstop → finishFullRecording (guarded below)
      streamRef.current?.getTracks().forEach((t) => t.stop());
      recRef.current?.stop();
    };
  }, []);

  const clearElapsedTimer = () => {
    if (elapsedTimerRef.current) { clearInterval(elapsedTimerRef.current); elapsedTimerRef.current = null; }
  };

  // Hand the finished transcript to the caller (append + auto-submit is theirs).
  // `wasEmptyOverride` forces the auto-submit signal: the Web-Speech fallback
  // passes false so a possibly-truncated transcript is NEVER auto-submitted —
  // only the authoritative server transcript honors the empty-at-start rule.
  const deliverTranscript = (text: string, wasEmptyOverride?: boolean) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    cbRef.current.onTranscript(trimmed, wasEmptyOverride ?? wasEmptyAtStartRef.current);
  };

  // Live ghost text only — never drives the transcript in "full" mode.
  const startSpeechGarnish = () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) return;
    try {
      const rec = new SR();
      rec.lang = "en-US";
      rec.interimResults = true;
      rec.continuous = true;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      rec.onresult = (e: any) => {
        let interim = "";
        let final = "";
        for (let i = 0; i < e.results.length; i++) {
          const chunk = e.results[i][0].transcript;
          if (e.results[i].isFinal) final += (final ? " " : "") + chunk;
          else interim += chunk;
        }
        speechFinalRef.current = final;
        setLiveInterim(interim || final);
      };
      rec.onerror = noop;
      recRef.current = rec;
      rec.start();
    } catch {
      // Web Speech unavailable/blocked — the recording still proceeds on the
      // server transcript alone.
    }
  };

  const startFullRecording = async () => {
    // Split the two failure modes: a getUserMedia rejection is a permission
    // denial (R-204 message), while a later MediaRecorder construction/start
    // throw is NOT a permission problem — and it leaves the mic OPEN, so its
    // tracks must be stopped or the OS mic indicator stays lit with no release.
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      cbRef.current.onError("Microphone blocked — allow access to use voice.");
      setRecording(false);
      return;
    }
    streamRef.current = stream;
    try {
      const mimeType = pickAudioMime((t) => MediaRecorder.isTypeSupported(t));
      const mr = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = () => { void finishFullRecording(mr.mimeType || mimeType || "audio/webm"); };
      mediaRecorderRef.current = mr;
      wasEmptyAtStartRef.current = cbRef.current.getInput().trim().length === 0;
      speechFinalRef.current = "";
      setLiveInterim("");
      mr.start();
      setRecording(true);
      setElapsedSec(0);
      elapsedTimerRef.current = setInterval(() => setElapsedSec((s) => s + 1), 1000);
      startSpeechGarnish();
    } catch {
      // Recorder construction/start failed — release the mic we just opened
      // before surfacing an honest, non-permission error.
      stream.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      mediaRecorderRef.current = null;
      cbRef.current.onError("Couldn't start recording.");
      setRecording(false);
    }
  };

  const finishFullRecording = async (mimeType: string) => {
    // onstop has fired → the recorder is now "inactive"; drop the ref so the
    // unmount cleanup never calls .stop() on a completed recorder.
    mediaRecorderRef.current = null;
    // A SPONTANEOUS stop (track ended: OS interruption, unplug, iOS lock,
    // permission revoked) reaches here WITHOUT going through stopRecording, which
    // is the only other place `recording`/the elapsed timer are reset. Reset them
    // here too, or the UI stays stuck on "Recording…" with a dead recorder and a
    // ticking timer — and a later tap would wedge the mic in "Transcribing…".
    setRecording(false);
    clearElapsedTimer();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recRef.current?.stop();
    recRef.current = null;
    setLiveInterim("");
    const chunks = chunksRef.current;
    chunksRef.current = [];
    // Torn down mid-recording — the mic is released above; nobody is listening,
    // so skip the wasted transcribe entirely.
    if (unmountedRef.current) { setTranscribing(false); return; }
    const blob = new Blob(chunks, { type: mimeType });
    if (blob.size === 0) { setTranscribing(false); return; }
    try {
      const { text } = await api.transcribe(blob);
      deliverTranscript(text);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        // STT unconfigured — fall back to the Web Speech garnish's accumulated
        // final transcript when it caught anything.
        const fallback = speechFinalRef.current.trim();
        if (fallback) {
          // Flag the possibly-truncated fallback and NEVER auto-submit it —
          // deliver with wasEmpty=false so the user reviews before submitting.
          cbRef.current.onError(WEB_SPEECH_FALLBACK_NOTICE);
          deliverTranscript(fallback, false);
        } else {
          cbRef.current.onError(err.message || "Voice transcription isn't set up — type instead.");
        }
      } else if (err instanceof Error) {
        cbRef.current.onError(err.message);
      } else {
        cbRef.current.onError("Couldn't transcribe that recording.");
      }
    } finally {
      setTranscribing(false);
      speechFinalRef.current = "";
    }
  };

  // Old-iOS-Safari fallback (no MediaRecorder): Web Speech drives the transcript
  // directly rather than just garnishing it.
  const startSpeechOnlyRecording = () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) return;
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.continuous = true;
    let finalText = "";
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const chunk = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += (finalText ? " " : "") + chunk;
        else interim += chunk;
      }
      setLiveInterim(interim);
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onerror = (e: any) => {
      cbRef.current.onError(e.error === "not-allowed" ? "Microphone blocked — allow access to use voice." : "Didn't catch that — try again.");
      setRecording(false);
      setLiveInterim("");
      clearElapsedTimer();
    };
    rec.onend = () => {
      setRecording(false);
      setLiveInterim("");
      clearElapsedTimer();
      deliverTranscript(finalText);
    };
    recRef.current = rec;
    wasEmptyAtStartRef.current = cbRef.current.getInput().trim().length === 0;
    rec.start();
    setRecording(true);
    setElapsedSec(0);
    elapsedTimerRef.current = setInterval(() => setElapsedSec((s) => s + 1), 1000);
  };

  const stopRecording = () => {
    clearElapsedTimer();
    setRecording(false);
    if (voiceMode === "full") {
      const mr = mediaRecorderRef.current;
      // Only enter "Transcribing…" when there's a LIVE recorder to stop. After a
      // spontaneous stop, finishFullRecording already ran and nulled the ref, so
      // there's nothing to stop — setting transcribing=true here would strand it
      // forever (nothing flips it back off), disabling the mic. MediaRecorder.stop()
      // also throws InvalidStateError on an already-"inactive" recorder, so guard.
      if (mr && mr.state !== "inactive") {
        setTranscribing(true); // optimistic — finishFullRecording flips it off
        mr.stop(); // → mr.onstop → finishFullRecording (guarded)
      }
      recRef.current?.stop(); // garnish recognizer, best effort
    } else {
      recRef.current?.stop(); // → rec.onend → deliverTranscript
    }
  };

  const toggleMic = () => {
    if (recording) { stopRecording(); return; }
    if (voiceMode === "none" || transcribing) return;
    cbRef.current.onError(null);
    if (voiceMode === "full") void startFullRecording();
    else startSpeechOnlyRecording();
  };

  return { voiceMode, recording, transcribing, elapsedSec, liveInterim, toggleMic };
}

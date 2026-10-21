"use client";

import { useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface VoiceInputButtonProps {
  onTranscript: (text: string) => void;
  disabled?: boolean;
}

export function VoiceInputButton({ onTranscript, disabled }: VoiceInputButtonProps) {
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const startRecording = async () => {
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        toast.error("Audio recording is not supported in this browser.");
        return;
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunksRef.current = [];

      // Prefer audio/webm, fall back to default
      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : MediaRecorder.isTypeSupported("audio/mp4")
          ? "audio/mp4"
          : "";

      const options = mimeType ? { mimeType } : undefined;
      const mediaRecorder = new MediaRecorder(stream, options);
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        // Stop all audio tracks
        stream.getTracks().forEach((track) => track.stop());

        const audioBlob = new Blob(audioChunksRef.current, {
          type: mimeType || "audio/webm",
        });

        if (audioBlob.size === 0) {
          return;
        }

        await uploadAndTranscribe(audioBlob);
      };

      mediaRecorder.start(250); // Slice into 250ms chunks
      setIsRecording(true);
    } catch (err) {
      console.error("Microphone access error:", err);
      toast.error("Microphone access denied or unavailable.");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const uploadAndTranscribe = async (blob: Blob) => {
    setIsTranscribing(true);
    try {
      const formData = new FormData();
      formData.append("file", blob, "recording.webm");

      const res = await api.post<{ text: string }>("/ai/transcribe", {
        body: formData,
      });

      if (res?.text && res.text.trim()) {
        onTranscript(res.text.trim());
        toast.success("Voice transcribed successfully");
      } else {
        toast.info("No speech recognized. Please try speaking again.");
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Audio transcription failed.";
      toast.error("Transcription error", { description: message });
    } finally {
      setIsTranscribing(false);
    }
  };

  if (isTranscribing) {
    return (
      <Button
        type="button"
        variant="ghost"
        size="icon"
        disabled
        className="size-8 text-primary shrink-0"
        aria-label="Transcribing audio"
      >
        <Loader2 className="size-4 animate-spin" />
      </Button>
    );
  }

  if (isRecording) {
    return (
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={stopRecording}
        className={cn(
          "size-8 text-danger shrink-0 bg-danger/10 hover:bg-danger/20 animate-pulse",
        )}
        aria-label="Stop voice recording"
        title="Stop recording"
      >
        <Square className="size-3.5 fill-danger" />
      </Button>
    );
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={startRecording}
      disabled={disabled}
      className="size-8 text-muted-foreground hover:text-foreground shrink-0"
      aria-label="Record voice prompt"
      title="Voice Input (Whisper)"
    >
      <Mic className="size-4" />
    </Button>
  );
}


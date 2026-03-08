import { useState } from "react";
import { uploadPresentationFile } from "@/lib/upload-service";

export function useFileUpload(sessionId: string) {
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUpload = async (file: File) => {
    if (!sessionId) {
      setError("Session not initialized. Please refresh the page.");
      return;
    }

    setIsUploading(true);
    setError(null);

    try {
      await uploadPresentationFile(file, sessionId);
      // We don't need to do anything else here because your onSnapshot
      // listener in usePresentation will automatically catch the Firestore update!
    } catch (err: any) {
      setError(err.message || "An unexpected error occurred.");
    } finally {
      setIsUploading(false);
    }
  };

  return {
    handleUpload,
    isUploading,
    error,
    clearError: () => setError(null),
  };
}

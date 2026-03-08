"use client";

import { useSession } from "@/components/providers/session-provider";
import { usePresentation } from "@/hooks/use-presentation";
import { useFileUpload } from "@/hooks/use-file-upload";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default function Home() {
  const { sessionId } = useSession();
  const { presentationData } = usePresentation(sessionId);
  const { handleUpload, isUploading, error } = useFileUpload(sessionId);

  const onFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleUpload(file);
    }
  };

  return (
    <main className="flex flex-col items-center justify-center p-24">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Generate Lecture</CardTitle>
          <CardDescription>Upload a chapter to begin</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">

          {/* Upload State */}
          {!presentationData && (
            <div className="space-y-4">
              <Input
                type="file"
                accept="application/pdf"
                onChange={onFileSelect}
                disabled={isUploading}
              />

              {/* Error Display */}
              {error && (
                <div className="text-sm text-red-500 bg-red-50 p-3 rounded-md border border-red-200">
                  {error}
                </div>
              )}

              <Button className="w-full" disabled={isUploading}>
                {isUploading ? "Uploading to Cloud..." : "Generate Lecture"}
              </Button>
            </div>
          )}

          {/* Processing State */}
          {presentationData?.status === "generating" && (
            <div className="text-center p-8 space-y-4">
              <div className="animate-pulse text-blue-600 font-medium">
                Extracting PDF and building slides...
              </div>
              <p className="text-xs text-muted-foreground">
                This usually takes about 45 seconds.
              </p>
            </div>
          )}

          {/* Ready State */}
          {presentationData?.status === "ready" && (
            <div className="text-center p-8 text-green-600 font-bold">
              Lecture is Ready! (Reveal.js initialization pending)
            </div>
          )}

        </CardContent>
      </Card>
    </main>
  );
}
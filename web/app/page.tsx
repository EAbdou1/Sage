"use client";

import { useSession } from "@/components/providers/session-provider";
import { usePresentation } from "@/hooks/use-presentation";
import { useFileUpload } from "@/hooks/use-file-upload";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import LoggerPanel, { LogEntry } from "@/components/logger-panel";
import SlideDeck from "@/components/slide-deck";

export default function Home() {
  const { sessionId } = useSession();
  const { presentationData } = usePresentation(sessionId);
  const { handleUpload, isUploading, error } = useFileUpload(sessionId);

  const onFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
  };

  const systemLogs: LogEntry[] = presentationData?.logs || [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 min-h-[calc(100vh-73px)]">

      {/* Left Side: Main Application Area (75% width on desktop) */}
      <main className="lg:col-span-3 flex flex-col items-center justify-center p-8 ">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Generate Lecture</CardTitle>
            <CardDescription>Upload a chapter to begin</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">

            {!presentationData && (
              <div className="space-y-4">
                <Input
                  type="file"
                  accept="application/pdf"
                  onChange={onFileSelect}
                  disabled={isUploading}
                />
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

            {presentationData?.status === "generating" && (
              <div className="text-center p-8 space-y-4">
                <div className="animate-pulse text-blue-600 font-medium">
                  Agents are analyzing the document...
                </div>
                <p className="text-xs text-muted-foreground">
                  Check the system logs on the right for live progress.
                </p>
              </div>
            )}

            {/* Ready State */}
            {presentationData?.status === "ready" && presentationData?.slides && (
              <div className="w-full animate-in fade-in zoom-in duration-500">
                <SlideDeck slides={presentationData.slides} />

                {/* A mock control panel for your voice agent later */}
                <div className="flex justify-center gap-4 mt-6">
                  <Button variant="outline" className="text-emerald-500 border-emerald-500">
                    🎤 Sage is Listening...
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </main>

      {/* Right Side: Live Logger Panel (25% width on desktop) */}
      <aside className="lg:col-span-1 border-l  h-[calc(100vh-73px)] overflow-hidden sticky top-0">
        <LoggerPanel logs={systemLogs} />
      </aside>

    </div>
  );
}
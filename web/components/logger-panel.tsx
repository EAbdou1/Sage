"use client";

import { useEffect, useRef } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";

export interface LogEntry {
  timestamp: string;
  agent: "System" | "ContentAgent" | "ReviewerAgent" | "SageAgent" | "MCQAgent" | "ExplainerAgent";
  message: string;
  type: "info" | "success" | "warning" | "error";
}

export default function LoggerPanel({ logs = [] }: { logs: LogEntry[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the latest log
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  const getAgentColor = (agent: string) => {
    switch (agent) {
      case "ContentAgent": return "bg-blue-500/10 text-blue-500 border-blue-500/20";
      case "ReviewerAgent": return "bg-purple-500/10 text-purple-500 border-purple-500/20";
      case "SageAgent": return "bg-green-500/10 text-green-500 border-green-500/20";
      case "ExplainerAgent": return "bg-orange-500/10 text-orange-500 border-orange-500/20";
      case "System": return "bg-slate-500/10 text-slate-500 border-slate-500/20";
      default: return "bg-gray-500/10 text-gray-500 border-gray-500/20";
    }
  };

  return (
    <div className="flex flex-col h-full border-l  font-mono text-xs">
      <div className="p-3 border-b  flex justify-between items-center">
        <span className="font-semibold text-slate-100 tracking-wider">SYSTEM.LOGS</span>
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          <span className="text-[10px] text-slate-400">LIVE</span>
        </div>
      </div>

      <ScrollArea className="flex-1 p-4">
        <div className="space-y-3">
          {logs.length === 0 ? (
            <div className="text-slate-600 text-center mt-10">Awaiting system events...</div>
          ) : (
            logs.map((log, index) => (
              <div key={index} className="flex flex-col gap-1 border-b border-slate-800/50 pb-2">
                <div className="flex items-center justify-between">
                  <Badge variant="outline" className={`text-[10px] px-1 py-0 h-4 rounded-sm ${getAgentColor(log.agent)}`}>
                    {log.agent}
                  </Badge>
                  <span className="text-slate-500 text-[9px]">
                    {new Date(log.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                <span className={`${log.type === 'error' ? 'text-red-400' : 'text-slate-300'}`}>
                  {log.message}
                </span>
              </div>
            ))
          )}
          <div ref={scrollRef} />
        </div>
      </ScrollArea>
    </div>
  );
}
"use client";

import React from 'react';
import { ModeToggle } from './mode-toggle';
import { useSession } from '@/components/providers/session-provider';

export default function Header() {
  const { sessionId } = useSession();

  return (
    <div className="p-4 border-b flex justify-between items-center w-full">
      <div className="flex items-center gap-4">
        <h1 className="text-2xl font-bold">SAGE AI</h1>
        {sessionId && (
          <span className="text-xs font-mono bg-muted px-2 py-1 rounded-md text-muted-foreground">
            ID: {sessionId.split('-')[0]}
          </span>
        )}
      </div>
      <div>
        <ModeToggle />
      </div>
    </div>
  );
}
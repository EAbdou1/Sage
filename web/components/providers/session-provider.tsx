"use client";

import React, { createContext, useContext, useState } from "react";
import { v4 as uuidv4 } from "uuid";

interface SessionContextType {
  sessionId: string;
}

const SessionContext = createContext<SessionContextType>({ sessionId: "" });

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [sessionId] = useState<string>(() => uuidv4());

  return (
    <SessionContext.Provider value={{ sessionId }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  return useContext(SessionContext);
}
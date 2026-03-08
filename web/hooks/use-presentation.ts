import { useState, useEffect } from "react";
import { doc, onSnapshot } from "firebase/firestore";
import { db } from "@/utils/firebase.browser";

export function usePresentation(sessionId: string) {
  const [presentationData, setPresentationData] = useState<any>(null);

  useEffect(() => {
    if (!sessionId) return;

    const docRef = doc(db, "presentations", sessionId);

    const unsubscribe = onSnapshot(docRef, (docSnap) => {
      if (docSnap.exists()) {
        setPresentationData(docSnap.data());
      }
    });

    return () => unsubscribe();
  }, [sessionId]);

  return { presentationData };
}

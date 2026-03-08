"use client";

import { useEffect, useRef, useState } from "react";
import Reveal from "reveal.js";
import "reveal.js/dist/reveal.css";
import "reveal.js/dist/theme/moon.css";

interface Slide {
  id: number;
  title: string;
  content: string;
  imageUrl?: string;
  isMCQ?: boolean;
  mcqOptions?: string[];
}

export default function SlideDeck({ slides }: { slides: Slide[] }) {
  const deckDivRef = useRef<HTMLDivElement>(null);
  const deckRef = useRef<Reveal.Api | null>(null);
  const [isRevealReady, setIsRevealReady] = useState(false);

  // 1. Initialize Reveal.js
  useEffect(() => {
    if (deckDivRef.current && !deckRef.current) {
      deckRef.current = new Reveal(deckDivRef.current, {
        embedded: true,
        keyboard: true,
        controls: true,
        progress: true,
        center: true,
        transition: "slide",
      });

      deckRef.current.initialize().then(() => {
        console.log("Reveal.js initialized successfully");
        setIsRevealReady(true); // Tell React that Reveal is done setting up
      });
    }

    // Cleanup on unmount
    return () => {
      try {
        if (deckRef.current) {
          deckRef.current.destroy();
          deckRef.current = null;
          setIsRevealReady(false);
        }
      } catch (e) {
        console.warn("Reveal.js cleanup warning", e);
      }
    };
  }, []);

  // 2. Safely Sync when slides change
  useEffect(() => {
    // Only sync if Reveal is fully initialized and ready
    if (deckRef.current && isRevealReady) {
      // setTimeout gives React one render cycle to actually put the new 
      // HTML <section> tags into the DOM before Reveal tries to find them.
      setTimeout(() => {
        try {
          deckRef.current?.sync();
        } catch (error) {
          console.error("Reveal sync error safely caught:", error);
        }
      }, 50);
    }
  }, [slides, isRevealReady]);

  if (!slides || slides.length === 0) return null;

  return (
    <div className="w-full h-[500px] border border-slate-700 rounded-xl overflow-hidden shadow-2xl relative">
      <div className="reveal" ref={deckDivRef}>
        <div className="slides">
          {slides.map((slide, index) => (
            <section key={index}>
              <h2 className="text-3xl font-bold mb-6 text-white">{slide.title}</h2>
              <p className="text-lg text-slate-300 mb-6">{slide.content}</p>

              {slide.imageUrl && (
                <img
                  src={slide.imageUrl}
                  alt={slide.title}
                  className="max-h-64 mx-auto rounded-lg shadow-lg border border-slate-600"
                />
              )}

              {slide.isMCQ && slide.mcqOptions && (
                <div className="grid grid-cols-2 gap-4 mt-8 max-w-2xl mx-auto">
                  {slide.mcqOptions.map((opt, i) => (
                    <div key={i} className="bg-slate-800 p-4 rounded border border-slate-600 text-sm">
                      {String.fromCharCode(65 + i)}. {opt}
                    </div>
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
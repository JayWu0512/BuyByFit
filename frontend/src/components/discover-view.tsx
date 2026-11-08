"use client";

import Image from "next/image";
import { FormEvent, useEffect, useRef, useState } from "react";

import { FurnitureCard } from "@/components/furniture-card";
import { RoomVisualizer } from "@/components/room-visualizer";
import { searchFurniture } from "@/lib/api";
import { FurnitureProduct } from "@/types/furniture";

interface SpeechRecognitionAlternativeLike {
  transcript: string;
}

interface SpeechRecognitionResultLike {
  0: SpeechRecognitionAlternativeLike;
  isFinal: boolean;
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  abort: () => void;
  start: () => void;
  stop: () => void;
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

const starterBriefs = [
  "A calm, light-filled living room with oak, linen, and space to breathe.",
  "A small rental bedroom that feels warm, practical, and not too precious.",
  "A dining corner with sculptural wood, soft light, and room for friends.",
];

const searchSessionKey = "buybyfit-room-brief";

function saveSearchState(brief: string, results: FurnitureProduct[]) {
  try {
    sessionStorage.setItem(searchSessionKey, JSON.stringify({ brief, results }));
  } catch {
    // The search still works when a browser denies session storage.
  }
}

function clearSearchState() {
  try {
    sessionStorage.removeItem(searchSessionKey);
  } catch {
    // The search still works when a browser denies session storage.
  }
}

export function DiscoverView() {
  const [brief, setBrief] = useState("");
  const [maxBudget, setMaxBudget] = useState("");
  const [submittedBrief, setSubmittedBrief] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [voiceMessage, setVoiceMessage] = useState("");
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<FurnitureProduct[]>([]);
  const [showCatalogNote, setShowCatalogNote] = useState(false);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const resultsRef = useRef<HTMLElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const catalogPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const catalogDismissTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const catalogLongPressRef = useRef(false);
  const results = searchResults;

  useEffect(() => {
    const recognitionWindow = window as typeof window & {
      SpeechRecognition?: SpeechRecognitionConstructor;
      webkitSpeechRecognition?: SpeechRecognitionConstructor;
    };
    setVoiceSupported(Boolean(recognitionWindow.SpeechRecognition || recognitionWindow.webkitSpeechRecognition));

    return () => recognitionRef.current?.abort();
  }, []);

  useEffect(() => {
    try {
      const savedSearch = sessionStorage.getItem(searchSessionKey);
      if (!savedSearch) return;

      const savedState = JSON.parse(savedSearch) as { brief?: unknown; results?: unknown };
      if (typeof savedState.brief !== "string" || savedState.brief.trim() === "") return;

      setBrief(savedState.brief);
      setSubmittedBrief(savedState.brief);
      if (Array.isArray(savedState.results)) {
        setSearchResults(savedState.results as FurnitureProduct[]);
      }
    } catch {
      clearSearchState();
    }
  }, []);

  useEffect(() => {
    if (!submittedBrief) return;

    resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    resultsRef.current?.focus({ preventScroll: true });
  }, [submittedBrief]);

  const submitBrief = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedBrief = brief.trim();

    if (!trimmedBrief) {
      setError("Tell us a little about the room before searching.");
      promptRef.current?.focus();
      return;
    }

    setError("");
    setIsSearching(true);
    const budget = maxBudget.trim() && Number.isFinite(Number(maxBudget)) ? Number(maxBudget) : undefined;
    try {
      const products = await searchFurniture(trimmedBrief, budget);
      setSearchResults(products);
      saveSearchState(trimmedBrief, products);
      setSubmittedBrief(trimmedBrief);
    } catch {
      setError("We couldn't reach the recommendation service. Check that the backend is running and try again.");
    } finally {
      setIsSearching(false);
    }
  };

  const startOver = () => {
    clearSearchState();
    setSubmittedBrief(null);
    setSearchResults([]);
    window.setTimeout(() => promptRef.current?.focus(), 0);
  };

  const clearCatalogPress = () => {
    if (catalogPressTimerRef.current) {
      clearTimeout(catalogPressTimerRef.current);
      catalogPressTimerRef.current = null;
    }
  };

  const beginCatalogPress = () => {
    clearCatalogPress();
    catalogLongPressRef.current = false;
    catalogPressTimerRef.current = setTimeout(() => {
      catalogLongPressRef.current = true;
      setShowCatalogNote(true);
      if (catalogDismissTimerRef.current) clearTimeout(catalogDismissTimerRef.current);
      catalogDismissTimerRef.current = setTimeout(() => setShowCatalogNote(false), 5000);
    }, 600);
  };

  const toggleVoiceInput = () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      return;
    }

    const recognitionWindow = window as typeof window & {
      SpeechRecognition?: SpeechRecognitionConstructor;
      webkitSpeechRecognition?: SpeechRecognitionConstructor;
    };
    const Recognition = recognitionWindow.SpeechRecognition ?? recognitionWindow.webkitSpeechRecognition;

    if (!Recognition) {
      setVoiceMessage("Voice input is not available in this browser. You can still type your room brief.");
      return;
    }

    const recognition = new Recognition();
    const startingBrief = brief.trim();
    recognition.lang = navigator.language || "en-US";
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let transcript = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        transcript += event.results[index][0]?.transcript ?? "";
      }

      const nextBrief = [startingBrief, transcript.trim()].filter(Boolean).join(startingBrief && transcript.trim() ? " " : "");
      if (nextBrief) {
        setBrief(nextBrief);
        setError("");
      }

      const lastResult = event.results[event.results.length - 1];
      setVoiceMessage(lastResult?.isFinal ? "Your words were added. You can keep speaking or refine the text." : "Listening…");
    };
    recognition.onerror = (event) => {
      const messages: Record<string, string> = {
        "no-speech": "We did not hear anything. Try again or type your brief.",
        "not-allowed": "Microphone permission was not granted. You can still type your brief.",
        "service-not-allowed": "Voice input is unavailable here. You can still type your brief.",
      };
      setVoiceMessage(messages[event.error] ?? "Voice input stopped. You can keep editing the text.");
      setIsListening(false);
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      setIsListening(false);
    };

    try {
      recognition.start();
      recognitionRef.current = recognition;
      setIsListening(true);
      setVoiceMessage("Listening… speak naturally about your room.");
    } catch {
      recognitionRef.current = null;
      setIsListening(false);
      setVoiceMessage("Voice input could not start. You can still type your brief.");
    }
  };

  return (
    <section className="search-experience" aria-labelledby={submittedBrief ? "results-heading" : "discover-heading"}>
      {!submittedBrief ? (
        <div className="search-prompt-stage">
          <div className="search-prompt-copy">
            <h1 id="discover-heading">Find what fits.</h1>

            <form className="room-search-form" onSubmit={submitBrief} noValidate>
              <div className="room-prompt-topline">
                <label className="room-prompt-label" htmlFor="room-brief">
                  Describe it your way
                </label>
                {voiceSupported ? (
                  <button
                    aria-pressed={isListening}
                    className={isListening ? "voice-button is-listening" : "voice-button"}
                    onClick={toggleVoiceInput}
                    type="button"
                  >
                    <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
                      <path d="M12 3.5a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0v-5a3 3 0 0 0-3-3Z" />
                      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M8.5 21h7" />
                    </svg>
                    {isListening ? "Listening" : "Use voice"}
                  </button>
                ) : null}
              </div>
              <div className="prompt-entry">
                <textarea
                  aria-describedby={error ? "room-brief-help room-brief-error" : "room-brief-help"}
                  aria-invalid={Boolean(error)}
                  id="room-brief"
                  name="room-brief"
                  onChange={(event) => {
                    setBrief(event.target.value);
                    if (error) setError("");
                  }}
                  placeholder="A quiet reading corner with warm wood, soft light, and one comfortable chair…"
                  ref={promptRef}
                  value={brief}
                />
              </div>
              <div className="prompt-entry-meta">
                <p className="room-prompt-help" id="room-brief-help">
                  Mention mood, light, materials, dimensions, budget, or what to avoid.
                </p>
                <p aria-live="polite" className="voice-status">
                  {voiceMessage}
                </p>
              </div>
              {error ? (
                <p className="room-prompt-error" id="room-brief-error" role="alert">
                  {error}
                </p>
              ) : null}

              <label className="budget-control" htmlFor="room-budget">
                <span>Max budget ($)</span>
                <input
                  id="room-budget"
                  inputMode="numeric"
                  min={0}
                  onChange={(event) => setMaxBudget(event.target.value)}
                  placeholder="No limit"
                  type="number"
                  value={maxBudget}
                />
              </label>

              <div className="prompt-actions">
                <button
                  aria-label="Find pieces. Press and hold for catalogue details."
                  className="button button-dark"
                  disabled={isSearching}
                  onClick={(event) => {
                    if (!catalogLongPressRef.current) return;
                    event.preventDefault();
                    catalogLongPressRef.current = false;
                  }}
                  onPointerCancel={clearCatalogPress}
                  onPointerDown={beginCatalogPress}
                  onPointerLeave={clearCatalogPress}
                  onPointerUp={clearCatalogPress}
                  type="submit"
                >
                  {isSearching ? "Searching…" : "Find pieces"}
                </button>
                {showCatalogNote ? (
                  <p className="search-catalog-note" role="status">
                    Results are ranked live by our recommendation service against a real product catalog.
                  </p>
                ) : null}
              </div>
            </form>

            <div className="starter-briefs" aria-label="Example room descriptions">
              <p>Start with one of these</p>
              <div>
                {starterBriefs.map((starterBrief) => (
                  <button
                    className="starter-brief"
                    key={starterBrief}
                    onClick={() => {
                      setBrief(starterBrief);
                      setError("");
                      promptRef.current?.focus();
                    }}
                    type="button"
                  >
                    {starterBrief}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="room-brief-mosaic" aria-label="Fictional Scandinavian interiors for atmosphere">
            <div className="brief-image brief-image-wide">
              <Image
                alt="Fictional Scandinavian living room with linen seating and warm oak"
                fill
                priority
                sizes="(max-width: 760px) 100vw, 44vw"
                src="/images/hjem-living-room.jpg"
                style={{ objectFit: "cover", objectPosition: "center" }}
              />
            </div>
            <div className="brief-image brief-image-tall">
              <Image
                alt="Fictional lounge chair in a quiet, sunlit room"
                fill
                sizes="(max-width: 760px) 50vw, 22vw"
                src="/images/hjem-lounge-chair.jpg"
                style={{ objectFit: "cover", objectPosition: "center" }}
              />
            </div>
            <div className="brief-image brief-image-square">
              <Image
                alt="Fictional travertine table with a warm material palette"
                fill
                sizes="(max-width: 760px) 50vw, 15vw"
                src="/images/hjem-travertine-table.jpg"
                style={{ objectFit: "cover", objectPosition: "center" }}
              />
            </div>
            <div className="brief-image brief-image-small">
              <Image
                alt="Fictional pendant light above a softly lit table"
                fill
                sizes="(max-width: 760px) 50vw, 15vw"
                src="/images/hjem-pendant-light.jpg"
                style={{ objectFit: "cover", objectPosition: "center" }}
              />
            </div>
          </div>
        </div>
      ) : (
        <section className="search-results" ref={resultsRef} tabIndex={-1} aria-labelledby="results-heading">
          <div className="search-results-topline">
            <div className="search-results-copy">
              <h1 id="results-heading">Furniture for your room</h1>
              <p className="submitted-brief-context">Your current theme</p>
              <p className="submitted-brief">“{submittedBrief}”</p>
            </div>

            <div className="results-actions">
              <button className="results-edit-brief" onClick={startOver} type="button">
                Change theme or room brief
              </button>
            </div>
          </div>

          {results.length > 0 ? <RoomVisualizer brief={submittedBrief} products={searchResults} /> : null}

          {results.length > 0 ? (
            <div className="furniture-grid">
              {results.map((product, index) => (
                <FurnitureCard
                  headingLevel={2}
                  key={product.id}
                  linkTo="detail"
                  priority={index < 4}
                  product={product}
                />
              ))}
            </div>
          ) : (
            <p className="no-results-note">
              We couldn&apos;t find a close match for that brief yet -- try describing the room differently, or check back as the catalog grows.
            </p>
          )}
        </section>
      )}
    </section>
  );
}

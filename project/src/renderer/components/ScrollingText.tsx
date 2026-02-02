import { useEffect, useRef } from "react";

export function ScrollingText({ text }: { text: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    const textEl = textRef.current;

    if (!container || !textEl) {return};

    const overflow = textEl.scrollWidth - container.clientWidth;

    if (overflow > 0) {
      textEl.animate(
        [
          { transform: "translateX(0)" },
          { transform: "translateX(0)" },
          { transform: `translateX(-${overflow}px)` },
          { transform: `translateX(-${overflow}px)` },
          { transform: "translateX(0)" }
        ],
        {
          duration: 8000,
          iterations: Infinity,
          easing: "ease-in-out"
        }
      );
    }
  }, []);

  return (
    <div ref={containerRef} className="scroll-container">
        <div ref={textRef} className="scroll-text">
            {text + "  "}
        </div>
    </div>
    
  );
}

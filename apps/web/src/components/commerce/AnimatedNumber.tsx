import { animate, useMotionValue } from "framer-motion";
import { useEffect, useState } from "react";

/** A figure that counts from its last value to the new one, formatted on every frame. */
export function AnimatedNumber({ value, format }: { value: number; format: (value: number) => string }) {
  const motionValue = useMotionValue(0);
  const [text, setText] = useState(() => format(0));

  useEffect(() => {
    // A new language reformats at once; the count then runs from wherever it was.
    setText(format(motionValue.get()));
    const controls = animate(motionValue, value, {
      duration: 0.8,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (latest) => setText(format(latest)),
    });
    return () => controls.stop();
  }, [value, format, motionValue]);

  return <span className="tabular-nums">{text}</span>;
}

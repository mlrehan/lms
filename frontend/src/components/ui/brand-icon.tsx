import type { SVGProps } from "react";
import { cn } from "@/lib/utils";

export function BrandIcon({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 396 548"
      fill="none"
      className={cn("h-6 w-auto shrink-0 aspect-[396/548]", className)}
      aria-hidden="true"
      {...props}
    >
      {/* Top Left Mouse Button */}
      <rect x="0" y="0" width="190" height="136" rx="3" fill="#FF0000" />

      {/* Top Right Mouse Button */}
      <rect x="206" y="0" width="190" height="136" rx="3" fill="#FF0000" />

      {/* Lower Shield Body: straight vertical sides down to 394, bottom U-curve to 548 */}
      <path d="M 0 152 H 396 V 394 C 396 480 300 548 198 548 C 96 548 0 480 0 394 Z" fill="#FF0000" />

      {/* Stylized White Outline Hand Cursor */}
      <g fill="none" stroke="#FFFFFF" strokeWidth="22" strokeLinecap="round" strokeLinejoin="round">
        {/* Extended Index Finger */}
        <path d="M 116 350 V 200 A 27.5 27.5 0 0 1 171 200 V 350" />

        {/* Folded Middle Finger */}
        <path d="M 171 268 A 25.5 25.5 0 0 1 222 268 V 345" />

        {/* Folded Ring Finger */}
        <path d="M 222 282 A 27.5 27.5 0 0 1 277 282 V 350" />

        {/* Folded Pinky Finger & Right Palm / Wrist */}
        <path d="M 277 298 A 20 20 0 0 1 317 298 V 420 C 317 460 302 510 275 540" />

        {/* Thumb & Left Palm / Wrist */}
        <path d="M 116 256 C 88 250 68 274 54 298 C 46 312 48 326 62 338 C 66 348 62 366 62 386 V 420 C 62 460 84 508 129 540" />
      </g>
    </svg>
  );
}

import type { SVGProps } from "react";
import { cn } from "@/lib/utils";

export function BrandIcon({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 512 512"
      fill="none"
      className={cn("size-6 shrink-0", className)}
      aria-hidden="true"
      {...props}
    >
      <defs>
        <linearGradient id="laitBrandRedSvg" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#FF1A24" />
          <stop offset="100%" stop-color="#D90412" />
        </linearGradient>
      </defs>

      {/* Top Left Mouse Button */}
      <path
        d="M 48 28 H 242 A 4 4 0 0 1 246 32 V 134 A 4 4 0 0 1 242 138 H 44 A 4 4 0 0 1 40 134 V 36 A 8 8 0 0 1 48 28 Z"
        fill="url(#laitBrandRedSvg)"
      />

      {/* Top Right Mouse Button */}
      <path
        d="M 270 28 H 464 A 8 8 0 0 1 472 36 V 134 A 4 4 0 0 1 468 138 H 270 A 4 4 0 0 1 266 134 V 32 A 4 4 0 0 1 270 28 Z"
        fill="url(#laitBrandRedSvg)"
      />

      {/* Lower Mouse Shield Body */}
      <path
        d="M 40 158 H 472 V 326 C 472 422 374 484 256 484 C 138 484 40 422 40 326 Z"
        fill="url(#laitBrandRedSvg)"
      />

      {/* White Hand Cursor Vector */}
      <g fill="none" stroke="#FFFFFF" stroke-width="22" stroke-linecap="round" stroke-linejoin="round">
        {/* Index Finger */}
        <path d="M 168 344 V 202 A 30 30 0 0 1 228 202 V 344" />

        {/* Middle Finger */}
        <path d="M 228 270 A 29 29 0 0 1 286 270 V 340" />

        {/* Ring Finger */}
        <path d="M 286 286 A 28 28 0 0 1 342 286 V 344" />

        {/* Pinky Finger & Right Palm */}
        <path d="M 342 302 A 23 23 0 0 1 388 302 V 370 C 388 410 376 440 358 458 L 336 474" />

        {/* Thumb & Left Palm */}
        <path d="M 168 306 C 146 290 126 270 112 272 C 96 274 90 288 92 304 C 94 324 104 336 104 358 C 104 382 100 406 102 426 C 104 450 118 466 142 472 L 176 474" />
      </g>
    </svg>
  );
}


import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import { CountBadge } from "./count-badge";

/**
 * The badge's whole job is to be small and still honest.
 *
 * Two things are worth protecting, and neither is visible to a typecheck: the
 * exact figure must always reach assistive technology regardless of what is
 * drawn, and a badge that is *not* abbreviated must not swallow a tap -- it
 * sits inside a navigation link, and stealing the click there would break
 * getting to the page for no benefit at all.
 */

afterEach(cleanup);

describe("CountBadge", () => {
  it("shows a small number in full", () => {
    render(<CountBadge count={7} label="waiting" />);
    expect(screen.getByRole("status")).toHaveTextContent("7");
  });

  it("abbreviates a large number", () => {
    render(<CountBadge count={1240} label="waiting" max={99} />);
    expect(screen.getByRole("status")).toHaveTextContent("99+");
  });

  it("always carries the exact figure in its accessible name", () => {
    render(<CountBadge count={1240} label="waiting" max={99} />);
    // A screen reader must never be told "99 plus". This is the reason the
    // reveal is an affordance rather than the only way to get the number.
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "1,240 waiting");
  });

  it("reveals the exact figure on hover", () => {
    render(<CountBadge count={1240} label="waiting" max={99} />);
    const badge = screen.getByRole("status");

    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.pointerEnter(badge, { pointerType: "mouse" });
    expect(screen.getByRole("tooltip")).toHaveTextContent("1,240 waiting");

    fireEvent.pointerLeave(badge);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("reveals the exact figure on a tap, and does not follow the link", () => {
    const onClick = vi.fn();
    render(
      // The real arrangement: the badge is inside a navigation link.
      <a href="/messages" onClick={onClick}>
        Messages
        <CountBadge count={1240} label="unread" max={99} />
      </a>,
    );
    const badge = screen.getByRole("status");

    fireEvent.click(badge);
    expect(screen.getByRole("tooltip")).toHaveTextContent("1,240 unread");
    // Tapping the badge specifically means wanting the number, not the page.
    expect(onClick).not.toHaveBeenCalled();
  });

  it("dismisses the reveal on a second tap", () => {
    render(<CountBadge count={1240} label="unread" max={99} />);
    const badge = screen.getByRole("status");

    fireEvent.click(badge);
    expect(screen.getByRole("tooltip")).not.toBeNull();
    fireEvent.click(badge);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("tidies the reveal away by itself", () => {
    vi.useFakeTimers();
    try {
      render(<CountBadge count={1240} label="unread" max={99} />);
      fireEvent.click(screen.getByRole("status"));
      expect(screen.queryByRole("tooltip")).not.toBeNull();

      // Otherwise a tapped badge stays open until something else is touched,
      // which on a phone is most of a session.
      //
      // Inside `act`, because the timer's state update is what re-renders;
      // advancing without it fires the callback and leaves the DOM showing
      // the previous render, which reads as the dismissal not working.
      act(() => void vi.advanceTimersByTime(3_000));
      expect(screen.queryByRole("tooltip")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("leaves a number that is already complete alone", () => {
    const onClick = vi.fn();
    render(
      <a href="/messages" onClick={onClick}>
        Messages
        <CountBadge count={3} label="unread" max={99} />
      </a>,
    );
    const badge = screen.getByRole("status");

    // Nothing to reveal, so nothing is stolen: the row navigates as it always
    // did. A badge showing "3" that swallowed taps would be a regression
    // nobody asked for.
    fireEvent.pointerEnter(badge, { pointerType: "mouse" });
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.click(badge);
    expect(onClick).toHaveBeenCalled();
    expect(badge).not.toHaveAttribute("tabindex");
  });

  it("does not open on the pointerenter that precedes a tap", () => {
    render(<CountBadge count={1240} label="unread" max={99} />);
    const badge = screen.getByRole("status");

    // Touch fires `pointerenter` immediately before the click. Opening on it
    // would make the first tap open and the click close again, so a tap would
    // appear to do nothing.
    fireEvent.pointerEnter(badge, { pointerType: "touch" });
    expect(screen.queryByRole("tooltip")).toBeNull();

    fireEvent.click(badge);
    expect(screen.getByRole("tooltip")).toHaveTextContent("1,240 unread");
  });

  it("is reachable and revealable from the keyboard", () => {
    render(<CountBadge count={1240} label="unread" max={99} />);
    const badge = screen.getByRole("status");
    expect(badge).toHaveAttribute("tabindex", "0");

    fireEvent.focus(badge);
    expect(screen.getByRole("tooltip")).toHaveTextContent("1,240 unread");
  });
});

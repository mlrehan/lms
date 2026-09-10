import { describe, expect, it } from "vitest";
import { ApiError, buildQuery, segment } from "./client";

describe("buildQuery", () => {
  it("omits absent values rather than sending them as empty", () => {
    // `?status=` is not the same request as no `status` at all: the server
    // would try to match the empty string.
    expect(buildQuery({ status: undefined, role: null, query: "" })).toBe("");
  });

  it("keeps false and zero, which are real values", () => {
    expect(buildQuery({ include_deleted: false, offset: 0 })).toBe("?include_deleted=false&offset=0");
  });

  it("repeats a key for an array, the way FastAPI reads a list", () => {
    expect(buildQuery({ types: ["course", "user"] })).toBe("?types=course&types=user");
  });

  it("encodes values that would otherwise break the query string", () => {
    expect(buildQuery({ q: "a&b=c d" })).toBe("?q=a%26b%3Dc+d");
  });

  it("returns an empty string, not a bare question mark, for no parameters", () => {
    expect(buildQuery(undefined)).toBe("");
    expect(buildQuery({})).toBe("");
  });
});

describe("segment", () => {
  it("encodes a path segment so it cannot escape its position", () => {
    expect(segment("../../admin")).toBe("..%2F..%2Fadmin");
    expect(segment("a b")).toBe("a%20b");
    expect(segment(42)).toBe("42");
  });
});

describe("ApiError", () => {
  it("prefers the server's own message", () => {
    const error = new ApiError(409, { code: "CONFLICT", message: "That batch code is taken." });
    expect(error.message).toBe("That batch code is taken.");
    expect(error.code).toBe("CONFLICT");
  });

  it("falls back to a readable message when the server sends none", () => {
    expect(new ApiError(403, {}).message).toBe("You do not have permission to do that.");
    expect(new ApiError(500, {}).message).toBe("The server could not complete that request.");
    expect(new ApiError(401, { message: "   " }).message).toBe(
      "Your session has ended. Please sign in again.",
    );
  });

  it("classifies the statuses screens branch on", () => {
    expect(new ApiError(401, {}).isUnauthenticated).toBe(true);
    expect(new ApiError(403, {}).isForbidden).toBe(true);
    expect(new ApiError(404, {}).isNotFound).toBe(true);
    expect(new ApiError(403, {}).isUnauthenticated).toBe(false);
  });

  it("extracts per-field messages a form can attach to an input", () => {
    const error = new ApiError(422, {
      details: { email: "Already in use.", roles: ["Unknown role"], nested: { a: 1 } },
    });
    expect(error.fieldErrors()).toEqual({ email: "Already in use.", roles: "Unknown role" });
  });
});

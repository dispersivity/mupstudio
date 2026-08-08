import { beforeEach, describe, expect, it, vi } from "vitest";
import { remembered } from "./remembered";

/**
 * Reloading is something people do constantly while building a model. Coming
 * back to a closed project on a step you were not on makes every reload feel
 * like starting over.
 */
describe("remembered", () => {
  beforeEach(() => {
    // jsdom in this project does not supply localStorage, and the module has to
    // work with and without it, so the test brings its own.
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
      clear: () => store.clear(),
      get length() {
        return store.size;
      },
      key: (index: number) => [...store.keys()][index] ?? null,
    });
  });

  it("opens on Project the first time, not on whatever the app starts with", () => {
    expect(remembered.step()).toBe("project");
  });

  it("comes back to the step you were on", () => {
    remembered.setStep("flow");
    expect(remembered.step()).toBe("flow");
  });

  it("ignores a step that no longer exists", () => {
    // Steps have been merged before — Domain went into Grid — and a stored id
    // from an older version would otherwise leave the shell rendering nothing.
    localStorage.setItem("mupstudio.step", "domain");
    expect(remembered.step()).toBe("project");
  });

  it("remembers the project by path", () => {
    remembered.setProject("/models/maipo.mup");
    expect(remembered.project()).toBe("/models/maipo.mup");
  });

  it("forgets the project when it is closed", () => {
    remembered.setProject("/models/maipo.mup");
    remembered.setProject(null);
    expect(remembered.project()).toBeNull();
  });

  it("stores only the path, never the model", () => {
    // The project on disk is the model. Anything cached here could be stale,
    // and a stale model is worse than no memory at all.
    remembered.setProject("/models/maipo.mup");

    expect(localStorage.getItem("mupstudio.project")!.length).toBeLessThan(500);
  });

  it("starts anyway when storage is refused", () => {
    // Private browsing and some embedded webviews throw on access. Forgetting
    // where you were is a small loss; failing to load is not.
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
      removeItem: () => {
        throw new Error("denied");
      },
    });

    expect(() => remembered.setStep("flow")).not.toThrow();
    expect(remembered.step()).toBe("project");
    expect(remembered.project()).toBeNull();
  });
});

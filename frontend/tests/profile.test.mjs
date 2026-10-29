import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function loadTypeScript(path) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}
const { createProfileController } = await loadTypeScript(
  "../src/features/profile/profile-state.ts",
);
const { ApiError, apiErrorFromException, apiErrorFromResponse } = await loadTypeScript(
  "../src/lib/api/errors.ts",
);
const { sessionFetch, setSessionProfile, subscribeSessionLoss } = await loadTypeScript(
  "../src/lib/api/profile-session.ts",
);
const missing = () =>
  new ApiError({ code: "session_required", status: 401, message: "Нет сессии" });
const profile = (id = "one", code = null) => ({ id, recovery_code: code });
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function setup(overrides = {}) {
  const calls = { read: 0, create: 0, restore: 0, remove: 0 };
  const requests = {
    read: async () => {
      calls.read++;
      throw missing();
    },
    create: async () => {
      calls.create++;
      return profile("one", "code-one");
    },
    restore: async () => {
      calls.restore++;
      return profile("existing");
    },
    remove: async () => {
      calls.remove++;
    },
    setSession: () => {},
    error: apiErrorFromException,
    ...overrides,
  };
  return { controller: createProfileController(requests), calls };
}

test("first opening only reads and offers an anonymous state; it never creates", async () => {
  const { controller, calls } = setup();
  await controller.load();
  assert.equal(controller.getSnapshot().profile.status, "anonymous");
  assert.deepEqual(calls, { read: 1, create: 0, restore: 0, remove: 0 });
});

test("Strict Mode duplicate loads and double creation clicks share each pending request", async () => {
  const read = deferred(),
    create = deferred();
  let reads = 0,
    creates = 0;
  const { controller } = setup({
    read: () => {
      reads++;
      return read.promise;
    },
    create: () => {
      creates++;
      return create.promise;
    },
  });
  const firstRead = controller.load(),
    secondRead = controller.load();
  assert.equal(firstRead, secondRead);
  const firstCreate = controller.create(),
    secondCreate = controller.create();
  assert.equal(firstCreate, secondCreate);
  create.resolve(profile("new", "correct-code"));
  await firstCreate;
  read.resolve(profile("old"));
  await firstRead;
  assert.equal(reads, 1);
  assert.equal(creates, 1);
  assert.equal(controller.getSnapshot().profile.profile.id, "new");
  assert.equal(controller.getSnapshot().pendingRecoveryCode, "correct-code");
});

test("GET of the same profile keeps the unclosed recovery code; dismissal stays dismissed", async () => {
  const { controller } = setup({ read: async () => profile() });
  await controller.create();
  await controller.load();
  assert.equal(controller.getSnapshot().pendingRecoveryCode, "code-one");
  controller.dismissCode();
  await controller.load();
  assert.equal(controller.getSnapshot().pendingRecoveryCode, null);
});

test("restore on a clean client never creates a temporary profile", async () => {
  const { controller, calls } = setup();
  await controller.load();
  await controller.restore("existing-code");
  assert.equal(calls.create, 0);
  assert.equal(calls.restore, 1);
  assert.equal(controller.getSnapshot().profile.profile.id, "existing");
  assert.equal(controller.getSnapshot().pendingRecoveryCode, null);
});

test("profile switch discards the previous recovery code", async () => {
  const { controller } = setup();
  await controller.create();
  await controller.restore("code-two");
  assert.equal(controller.getSnapshot().profile.profile.id, "existing");
  assert.equal(controller.getSnapshot().pendingRecoveryCode, null);
});

test("deletion followed by polling or another tab notification never creates", async () => {
  const { controller, calls } = setup();
  await controller.create();
  await controller.remove();
  await controller.load();
  assert.equal(controller.getSnapshot().profile.status, "deleted");
  await controller.sessionChanged();
  assert.equal(controller.getSnapshot().profile.status, "deleted");
  assert.equal(calls.create, 1);
  assert.equal(calls.remove, 1);
  assert.equal(controller.getSnapshot().pendingRecoveryCode, null);
});

test("session loss clears ready state and recovery code without creation", async () => {
  const { controller, calls } = setup();
  await controller.create();
  controller.sessionLost();
  assert.equal(controller.getSnapshot().profile.status, "anonymous");
  assert.equal(controller.getSnapshot().pendingRecoveryCode, null);
  assert.equal(calls.create, 1);
});

test("cross-tab signal during creation rechecks the cookie after the mutation", async () => {
  const creating = deferred();
  let reads = 0;
  const { controller } = setup({
    create: () => creating.promise,
    read: async () => {
      reads++;
      return profile("new");
    },
  });
  const mutation = controller.create();
  const changed = controller.sessionChanged();
  creating.resolve(profile("new", "new-code"));
  await Promise.all([mutation, changed]);
  assert.equal(reads, 1);
  assert.equal(controller.getSnapshot().profile.status, "ready");
  assert.equal(controller.getSnapshot().pendingRecoveryCode, "new-code");
});

test("temporary read failure does not lose the code when the same profile is read again", async () => {
  let fail = true;
  const { controller } = setup({
    read: async () => {
      if (fail) throw new Error("network");
      return profile();
    },
  });
  await controller.create();
  await controller.load();
  fail = false;
  await controller.load();
  assert.equal(controller.getSnapshot().pendingRecoveryCode, "code-one");
});

test("invalid restore preserves the anonymous form and the old profile's unclosed code", async () => {
  const { controller } = setup({
    restore: async () => {
      throw new ApiError({ code: "invalid_recovery_code", status: 400, message: "Не подходит" });
    },
  });
  await controller.load();
  const restoring = controller.restore("typo");
  assert.equal(controller.getSnapshot().profile.status, "anonymous");
  await assert.rejects(restoring);
  assert.equal(controller.getSnapshot().profile.status, "anonymous");
  await controller.create();
  await assert.rejects(controller.restore("typo"));
  assert.equal(controller.getSnapshot().profile.status, "ready");
  assert.equal(controller.getSnapshot().pendingRecoveryCode, "code-one");
});

test("401 recognition reaches the controller and stops subsequent profile network calls", async (t) => {
  let network = 0;
  t.mock.method(globalThis, "fetch", async () => {
    network++;
    return new Response(null, { status: 401 });
  });
  const { controller } = setup({ setSession: setSessionProfile });
  await controller.create();
  const unsubscribe = subscribeSessionLoss(controller.sessionLost);
  try {
    await sessionFetch("/api/events");
    assert.equal(controller.getSnapshot().profile.status, "anonymous");
    for (const path of [
      "/api/events",
      "/api/dialog",
      "/api/chat",
      "/api/voice",
      "/api/tts",
      "/api/calendar.ics",
    ]) {
      assert.equal((await sessionFetch(path)).status, 401);
    }
    assert.equal(network, 1);
  } finally {
    unsubscribe();
    setSessionProfile(null);
  }
});

test("late 401 from the old profile cannot revoke a newly created session", async (t) => {
  const old = deferred();
  t.mock.method(globalThis, "fetch", () => old.promise);
  let losses = 0;
  const unsubscribe = subscribeSessionLoss(() => {
    losses++;
  });
  try {
    setSessionProfile("old");
    const request = sessionFetch("/api/events");
    setSessionProfile("new");
    old.resolve(new Response(null, { status: 401 }));
    await request;
    assert.equal(losses, 0);
  } finally {
    unsubscribe();
    setSessionProfile(null);
  }
});

test("new auth and creation refusal codes are recognized by the API client", () => {
  for (const [code, status] of [
    ["session_required", 401],
    ["forbidden", 403],
  ]) {
    const error = apiErrorFromResponse(new Response(null, { status }), {
      error: { code, message: code },
    });
    assert.equal(error.code, code);
  }
});

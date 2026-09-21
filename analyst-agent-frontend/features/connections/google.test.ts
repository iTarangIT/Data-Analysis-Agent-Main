import { describe, expect, it } from "vitest";

import type { DatasetSource, DriveNode, ResolveResult, Rule } from "@/lib/api/types";

import {
  type LinkStep,
  isCovered,
  nextStep,
  rowState,
  ruleFor,
  rulesFor,
  toggleRule,
} from "./google";

const LINK = "https://drive.google.com/drive/folders/abc";

function source(over: Partial<DatasetSource> = {}): DatasetSource {
  return {
    id: "s1",
    origin: "gdrive_folder",
    label: "Sales",
    status: "pending",
    combine: true,
    rules: [],
    files: [],
    ...over,
  };
}

function reply(over: Partial<ResolveResult>): ResolveResult {
  return { status: "resolved", share_with: null, source: null, ...over };
}

function node(id: string, kind: DriveNode["kind"], supported = true): DriveNode {
  return { id, name: id, kind, supported, bytes: null };
}

const checking: LinkStep = { step: "checking", url: LINK, confirm: false };

describe("nextStep", () => {
  it("starts checking a pasted link", () => {
    expect(nextStep({ step: "idle" }, { type: "check", url: LINK })).toEqual(checking);
  });

  it("asks for the link to be shared, then checks the same link again, then resolves it", () => {
    const needsShare = nextStep(checking, {
      type: "reply",
      result: reply({ status: "needs_share", share_with: "reader@proj.iam.gserviceaccount.com" }),
    });
    expect(needsShare).toEqual({
      step: "needs_share",
      url: LINK,
      shareWith: "reader@proj.iam.gserviceaccount.com",
    });

    const again = nextStep(needsShare, { type: "check", url: LINK });
    expect(again).toEqual(checking);

    const found = source();
    expect(nextStep(again, { type: "reply", result: reply({ source: found }) })).toEqual({
      step: "resolved",
      url: LINK,
      source: found,
    });
  });

  it("lets an owner confirm an unverified link, which checks it again with the confirmation", () => {
    const unverified = nextStep(checking, { type: "reply", result: reply({ status: "unverified" }) });
    expect(unverified).toEqual({ step: "unverified", url: LINK });

    expect(nextStep(unverified, { type: "confirm", owner: true })).toEqual({
      step: "checking",
      url: LINK,
      confirm: true,
    });
  });

  it("will not confirm an unverified link for someone who is not an owner", () => {
    const unverified: LinkStep = { step: "unverified", url: LINK };

    expect(nextStep(unverified, { type: "confirm", owner: false })).toBe(unverified);
  });

  it("says why a check failed, and lets another link be checked", () => {
    const failed = nextStep(checking, {
      type: "fail",
      message: "paste a Google Drive or Google Sheets link",
    });
    expect(failed).toEqual({
      step: "failed",
      url: LINK,
      message: "paste a Google Drive or Google Sheets link",
    });

    expect(nextStep(failed, { type: "check", url: "https://docs.google.com/x" })).toEqual({
      step: "checking",
      url: "https://docs.google.com/x",
      confirm: false,
    });
  });

  it("treats a share request with no address to share with as a failure", () => {
    expect(nextStep(checking, { type: "reply", result: reply({ status: "needs_share" }) })).toEqual({
      step: "failed",
      url: LINK,
      message: "That link could not be checked. Try again.",
    });
  });

  it("ignores a second check while one is running, and a reply when nothing is running", () => {
    expect(nextStep(checking, { type: "check", url: "https://other" })).toBe(checking);

    const idle: LinkStep = { step: "idle" };
    expect(nextStep(idle, { type: "reply", result: reply({ source: source() }) })).toBe(idle);
    expect(nextStep(idle, { type: "confirm", owner: true })).toBe(idle);
  });
});

describe("rules", () => {
  it("turns a folder into a folder rule and anything else in a folder into a file rule", () => {
    expect(ruleFor("gdrive_folder", node("f1", "folder"))).toEqual({
      id: "f1",
      kind: "folder",
      recursive: false,
    });
    expect(ruleFor("gdrive_folder", node("s1", "sheet"))).toEqual({
      id: "s1",
      kind: "file",
      recursive: false,
    });
  });

  it("turns a spreadsheet's tab into a sheet rule", () => {
    expect(ruleFor("gsheet", node("0", "sheet"))).toEqual({ id: "0", kind: "sheet", recursive: false });
  });

  it("adds a rule, then takes it away again, without changing the list it was given", () => {
    const start: Rule[] = [{ id: "a", kind: "file", recursive: false }];
    const folder: Rule = { id: "f", kind: "folder", recursive: false };

    const added = toggleRule(start, folder);
    expect(added).toEqual([...start, folder]);
    expect(toggleRule(added, folder)).toEqual(start);
    expect(start).toHaveLength(1);
  });

  it("applies include subfolders to every folder rule and to nothing else", () => {
    const chosen: Rule[] = [
      { id: "f", kind: "folder", recursive: false },
      { id: "a", kind: "file", recursive: false },
    ];

    expect(rulesFor(chosen, true)).toEqual([
      { id: "f", kind: "folder", recursive: true },
      { id: "a", kind: "file", recursive: false },
    ]);
    expect(rulesFor(chosen, false)[0]?.recursive).toBe(false);
  });
});

describe("isCovered", () => {
  const rules: Rule[] = [{ id: "root", kind: "folder", recursive: false }];

  it("covers everything under a chosen folder at any depth when subfolders are included", () => {
    expect(isCovered(node("a", "csv"), ["root", "sub", "deeper"], rules, true)).toBe(true);
    expect(isCovered(node("sub", "folder"), ["root"], rules, true)).toBe(true);
  });

  it("covers only the files directly inside a chosen folder when subfolders are left out", () => {
    expect(isCovered(node("a", "csv"), ["root"], rules, false)).toBe(true);
    expect(isCovered(node("sub", "folder"), ["root"], rules, false)).toBe(false);
    expect(isCovered(node("b", "csv"), ["root", "sub"], rules, false)).toBe(false);
  });

  it("does not cover anything from a chosen file", () => {
    expect(isCovered(node("a", "csv"), ["x"], [{ id: "x", kind: "file", recursive: false }], true)).toBe(
      false,
    );
  });
});

describe("rowState", () => {
  const rules: Rule[] = [{ id: "root", kind: "folder", recursive: false }];

  it("shows a covered row as ticked and locked", () => {
    expect(rowState(node("a", "csv"), ["root"], rules, true)).toEqual({ checked: true, disabled: true });
  });

  it("never lets an unsupported file be chosen, even under a chosen folder", () => {
    expect(rowState(node("notes", "other", false), ["root"], rules, true)).toEqual({
      checked: false,
      disabled: true,
    });
  });

  it("shows a row as ticked only when it has its own rule", () => {
    expect(rowState(node("root", "folder"), [], rules, true)).toEqual({ checked: true, disabled: false });
    expect(rowState(node("other", "folder"), [], rules, true)).toEqual({
      checked: false,
      disabled: false,
    });
  });
});

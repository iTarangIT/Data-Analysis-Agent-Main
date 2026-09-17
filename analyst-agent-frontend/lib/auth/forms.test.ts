import { describe, expect, it } from "vitest";

import { fieldErrors, RegisterSchema, WelcomeSchema } from "./forms";

const valid = {
  email: "owner@example.com",
  password: "a-long-enough-password",
  tenant_name: "Acme Logistics",
};

describe("RegisterSchema", () => {
  /** The organisation is created from this name when the confirmation link is opened. */
  it("needs an organisation name", () => {
    const result = RegisterSchema.safeParse({ ...valid, tenant_name: "" });

    expect(result.success).toBe(false);
    expect(fieldErrors(result.error!)).toHaveProperty("tenant_name");
  });

  it("refuses a name that is only spaces", () => {
    expect(RegisterSchema.safeParse({ ...valid, tenant_name: "   " }).success).toBe(false);
  });

  it("trims the organisation name and the email", () => {
    const result = RegisterSchema.parse({
      ...valid,
      email: "  owner@example.com ",
      tenant_name: "  Acme  ",
    });

    expect(result.email).toBe("owner@example.com");
    expect(result.tenant_name).toBe("Acme");
  });

  it.each(["x".repeat(11), "x".repeat(129)])("refuses a password of %s characters", (password) => {
    const result = RegisterSchema.safeParse({ ...valid, password });

    expect(fieldErrors(result.error!)).toHaveProperty("password");
  });
});

describe("WelcomeSchema", () => {
  it.each(["", "   "])("refuses a blank organisation name (%j)", (tenant_name) => {
    const result = WelcomeSchema.safeParse({ tenant_name });

    expect(fieldErrors(result.error!)).toEqual({ tenant_name: "Name your organisation." });
  });

  it("refuses a name longer than the agent stores", () => {
    expect(WelcomeSchema.safeParse({ tenant_name: "x".repeat(201) }).success).toBe(false);
  });

  it("trims the name", () => {
    expect(WelcomeSchema.parse({ tenant_name: " Acme " }).tenant_name).toBe("Acme");
  });
});

describe("fieldErrors", () => {
  it("keeps the first message per field", () => {
    const result = RegisterSchema.safeParse({ email: "nope", password: "", tenant_name: "" });

    const errors = fieldErrors(result.error!);
    expect(Object.keys(errors).sort()).toEqual(["email", "password", "tenant_name"]);
    expect(errors.email).toBe("Enter a valid email address.");
  });
});

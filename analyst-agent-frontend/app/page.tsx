import { redirect } from "next/navigation";

/** proxy.ts has already decided whether there is a session, so this only needs to point. */
export default function Home() {
  redirect("/ask");
}

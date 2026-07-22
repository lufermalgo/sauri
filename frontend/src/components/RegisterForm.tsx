import React, { useState } from "react";
import { registerMeeting } from "../api";

const MEET_LINK_PATTERN = /^https:\/\/meet\.google\.com\/.+$/;

interface RegisterFormProps {
  onRegistered: () => void;
}

export function RegisterForm({ onRegistered }: RegisterFormProps) {
  const [meetLink, setMeetLink] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const isValid = MEET_LINK_PATTERN.test(meetLink.trim());

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!isValid) {
      setError("The link must be a valid Google Meet URL (https://meet.google.com/...)");
      return;
    }

    setLoading(true);
    try {
      await registerMeeting(meetLink.trim());
      setMeetLink("");
      onRegistered();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to register the meeting");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section>
      <h2>Register Meeting</h2>
      <form onSubmit={handleSubmit}>
        <label htmlFor="meet-link">Google Meet link</label>
        <input
          id="meet-link"
          type="url"
          placeholder="https://meet.google.com/abc-defg-hij"
          value={meetLink}
          onChange={(e) => setMeetLink(e.target.value)}
          required
          aria-invalid={meetLink.length > 0 && !isValid ? true : undefined}
        />
        <button type="submit" disabled={!isValid || loading}>
          {loading ? "Registering..." : "Register"}
        </button>
        {error && <p role="alert" style={{ color: "red" }}>{error}</p>}
      </form>
    </section>
  );
}

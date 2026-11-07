// Every call to the FastAPI backend goes through here.

// Turn whatever the server sent back into one friendly sentence.
function errorMessage(data) {
  const fallback = 'Something went wrong. Please try again.';
  if (!data || !data.detail) return fallback;
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail) && data.detail[0]?.msg) {
    // Pydantic prefixes custom messages with "Value error, ".
    return data.detail[0].msg.replace(/^Value error,\s*/i, '');
  }
  return fallback;
}

export async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
  } catch {
    throw new Error("We couldn't reach the server. Check it is running and try again.");
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    // Some responses have no body; that is fine.
  }

  if (!response.ok) throw new Error(errorMessage(data));
  return data;
}

let profilesPromise = null;

// The demo tester and manager, fetched once per page.
export function getProfiles() {
  if (!profilesPromise) {
    profilesPromise = api('/api/profiles').catch((error) => {
      profilesPromise = null;
      throw error;
    });
  }
  return profilesPromise;
}

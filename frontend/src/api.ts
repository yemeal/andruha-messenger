export type CurrentUser = {
  id: string;
  email: string;
  role: string;
  createdAt: string;
};
export type Profile = {
  user_id: string;
  username: string | null;
  display_name: string;
  bio: string | null;
  avatar_key: string | null;
  version: number;
};
export type PublicProfile = Pick<
  Profile,
  "user_id" | "username" | "display_name" | "bio" | "avatar_key"
>;
export type RegistrationResult = {
  userId: string;
  registrationId?: string;
  status?: "PENDING";
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    detail: string,
  ) {
    super(detail);
  }
}

async function request(path: string, init: RequestInit = {}) {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError(
      0,
      "network.unavailable",
      "Не удалось связаться с сервером. Проверьте подключение и попробуйте снова.",
    );
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      code?: string;
      detail?: string;
    };
    throw new ApiError(
      response.status,
      body.code ?? "request.failed",
      body.detail ?? "Сервер не смог выполнить запрос.",
    );
  }
  return response;
}

let refreshPromise: Promise<void> | null = null;
async function refreshSession() {
  if (!refreshPromise) {
    refreshPromise = request("/api/v1/auth/refresh", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    })
      .then(() => undefined)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

async function authenticated(path: string, init: RequestInit = {}) {
  try {
    return await request(path, init);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    await refreshSession();
    return request(path, init);
  }
}

export async function register(email: string, password: string, key: string) {
  const response = await request("/api/v1/auth/register", {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify({ email, password }),
  });
  return {
    status: response.status,
    value: (await response.json()) as RegistrationResult,
    retryAfter: Number(response.headers.get("Retry-After") ?? 1),
  };
}

export async function login(email: string, password: string) {
  await request("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function logout() {
  await request("/api/v1/auth/logout", { method: "POST" });
}

export async function getCurrentUser(): Promise<CurrentUser> {
  const response = await authenticated("/api/v1/auth/me");
  return response.json();
}

export async function getMyProfile(): Promise<Profile> {
  const response = await authenticated("/api/v1/profiles/me");
  return response.json();
}

export async function updateMyProfile(
  profile: Profile,
  data: { display_name?: string; username?: string; bio?: string | null },
): Promise<Profile> {
  const response = await authenticated("/api/v1/profiles/me", {
    method: "PATCH",
    headers: {
      "If-Match": `"${profile.version}"`,
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify(data),
  });
  return response.json();
}

export async function findProfile(username: string): Promise<PublicProfile> {
  const response = await authenticated(
    `/api/v1/profiles?username=${encodeURIComponent(username)}`,
  );
  return response.json();
}

export function humanError(error: unknown) {
  if (!(error instanceof ApiError))
    return "Что-то пошло не так. Попробуйте ещё раз.";
  const messages: Record<string, string> = {
    "auth.email_already_exists":
      "Этот адрес уже зарегистрирован. Попробуйте войти.",
    "auth.invalid_credentials": "Почта или пароль не подошли.",
    "auth.profile_provisioning_unavailable":
      "Профиль пока создаётся. Повторите запрос чуть позже.",
    "auth.idempotency_request_in_progress":
      "Запрос ещё обрабатывается. Подождите пару секунд.",
    "request.validation_error": "Проверьте данные в форме.",
  };
  if (error.status === 404) return "Пользователь с таким ником не найден.";
  if (error.status === 503)
    return "Сервис временно недоступен. Попробуйте позже.";
  return (
    messages[error.code] ??
    (error.status === 0
      ? error.message
      : "Не удалось выполнить запрос. Попробуйте ещё раз.")
  );
}

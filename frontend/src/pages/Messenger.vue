<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  MessageCircle,
  Plus,
  Search,
  Send,
  Settings2,
  Sparkles,
  X,
} from "@lucide/vue";
import {
  ApiError,
  findProfile,
  getCurrentUser,
  getMyProfile,
  humanError,
  logout,
  updateMyProfile,
  type CurrentUser,
  type Profile,
  type PublicProfile,
} from "../api";

const props = defineProps<{ demo: boolean }>();
const router = useRouter();
type Message = { id: string; text: string; mine: boolean; time: string };
type Chat = {
  id: string;
  name: string;
  initial: string;
  tint: string;
  preview: string;
  unread?: number;
  online?: boolean;
  messages: Message[];
};
const chats = ref<Chat[]>([
  {
    id: "masha",
    name: "Маша Соколова",
    initial: "М",
    tint: "peach",
    preview: "Кажется, это мы после прогулки",
    unread: 2,
    online: true,
    messages: [
      {
        id: "1",
        text: "Смотри, какое сегодня небо!",
        mine: false,
        time: "14:30",
      },
      { id: "2", text: "Теперь точно пора гулять", mine: true, time: "14:31" },
      {
        id: "3",
        text: "Кажется, это мы после прогулки ☁️",
        mine: false,
        time: "14:32",
      },
    ],
  },
  {
    id: "sasha",
    name: "Саша",
    initial: "С",
    tint: "lavender",
    preview: "Фото получилось классным!",
    unread: 1,
    messages: [
      { id: "1", text: "Я сохранил наше фото", mine: false, time: "13:18" },
      {
        id: "2",
        text: "Фото получилось классным!",
        mine: false,
        time: "13:20",
      },
    ],
  },
  {
    id: "danya",
    name: "Даня",
    initial: "Д",
    tint: "mint",
    preview: "Пятница, 19:00. Записал!",
    messages: [
      { id: "1", text: "Пятница, 19:00. Записал!", mine: false, time: "12:46" },
    ],
  },
  {
    id: "mama",
    name: "Мама",
    initial: "М",
    tint: "butter",
    preview: "Ты шапку-то возьми с собой",
    messages: [
      {
        id: "1",
        text: "Ты шапку-то возьми с собой",
        mine: false,
        time: "11:09",
      },
      { id: "2", text: "Хорошо ❤️", mine: true, time: "11:12" },
    ],
  },
]);
const user = ref<CurrentUser | null>(null);
const profile = ref<Profile | null>(null);
const sessionLoading = ref(!props.demo);
const sessionError = ref("");
const activeId = ref<string | null>(props.demo ? "masha" : null);
const activeChat = computed(() =>
  props.demo
    ? chats.value.find((chat) => chat.id === activeId.value)
    : undefined,
);
const search = ref("");
const filter = ref<"all" | "unread">("all");
const filtered = computed(() =>
  props.demo
    ? chats.value.filter(
        (chat) =>
          chat.name.toLowerCase().includes(search.value.toLowerCase()) &&
          (filter.value === "all" || chat.unread),
      )
    : [],
);
const draft = ref("");
const messagesEnd = ref<HTMLElement | null>(null);
const modal = ref<"profile" | "find" | null>(null);
const lookup = ref("");
const found = ref<PublicProfile | null>(null);
const lookupError = ref("");
const lookupBusy = ref(false);
const editName = ref("");
const editUsername = ref("");
const editBio = ref("");
const saveError = ref("");
const saveBusy = ref(false);

onMounted(async () => {
  if (props.demo) return;
  try {
    user.value = await getCurrentUser();
    try {
      profile.value = await getMyProfile();
    } catch {
      /* The profile dialog exposes this failure. */
    }
  } catch (cause) {
    if (
      cause instanceof ApiError &&
      (cause.status === 401 || cause.status === 403)
    ) {
      await router.replace("/login");
      return;
    }
    sessionError.value = humanError(cause);
  } finally {
    sessionLoading.value = false;
  }
});

function chooseChat(id: string) {
  activeId.value = id;
  chats.value = chats.value.map((chat) =>
    chat.id === id ? { ...chat, unread: 0 } : chat,
  );
  nextTick(() => messagesEnd.value?.scrollIntoView({ behavior: "smooth" }));
}
function sendMessage() {
  const text = draft.value.trim();
  if (!text || !activeId.value) return;
  chats.value = chats.value.map((chat) =>
    chat.id === activeId.value
      ? {
          ...chat,
          preview: text,
          messages: [
            ...chat.messages,
            {
              id: crypto.randomUUID(),
              text,
              mine: true,
              time: new Date().toLocaleTimeString("ru", {
                hour: "2-digit",
                minute: "2-digit",
              }),
            },
          ],
        }
      : chat,
  );
  draft.value = "";
  nextTick(() => messagesEnd.value?.scrollIntoView({ behavior: "smooth" }));
}
function openProfile() {
  editName.value = profile.value?.display_name ?? "";
  editUsername.value = profile.value?.username ?? "";
  editBio.value = profile.value?.bio ?? "";
  saveError.value = "";
  modal.value = "profile";
}
function closeModal() {
  modal.value = null;
  saveError.value = "";
  lookupError.value = "";
}
function onEscape(event: KeyboardEvent) {
  if (event.key === "Escape") closeModal();
}
onMounted(() => window.addEventListener("keydown", onEscape));
onUnmounted(() => window.removeEventListener("keydown", onEscape));
async function find() {
  lookupError.value = "";
  found.value = null;
  lookupBusy.value = true;
  try {
    found.value = await findProfile(lookup.value.trim().replace(/^@/, ""));
  } catch (cause) {
    lookupError.value = humanError(cause);
  } finally {
    lookupBusy.value = false;
  }
}
async function save() {
  if (!profile.value) return;
  if (profile.value.username && !editUsername.value.trim()) {
    saveError.value = "Ник нельзя оставить пустым.";
    return;
  }
  saveError.value = "";
  saveBusy.value = true;
  try {
    profile.value = await updateMyProfile(profile.value, {
      display_name: editName.value.trim(),
      username: editUsername.value.trim() || undefined,
      bio: editBio.value.trim(),
    });
    closeModal();
  } catch (cause) {
    saveError.value = humanError(cause);
  } finally {
    saveBusy.value = false;
  }
}
async function signOut() {
  if (props.demo) {
    await router.push("/");
    return;
  }
  try {
    await logout();
    await router.push("/");
  } catch (cause) {
    saveError.value = humanError(cause);
  }
}
function retry() {
  window.location.reload();
}
</script>

<template>
  <div v-if="sessionLoading" class="session-state">
    <img src="/fox-front.png" alt="Белоснежный лис ждёт" />
    <p>Заглядываем в твои разговоры…</p>
  </div>
  <div v-else-if="sessionError" class="session-state">
    <img src="/fox-front.png" alt="Белоснежный лис ждёт" />
    <p>{{ sessionError }}</p>
    <button class="pill-button" @click="retry">
      Повторить <ArrowRight :size="17" />
    </button>
  </div>
  <main v-else :class="['messenger', { 'has-chat': activeId }]">
    <nav class="app-rail" aria-label="Разделы">
      <RouterLink class="rail-brand" to="/" aria-label="На главную"
        ><img src="/fox-front.png" alt="" /></RouterLink
      ><button class="rail-item selected" aria-label="Чаты">
        <MessageCircle :size="21" /></button
      ><button
        class="rail-item"
        aria-label="Найти человека"
        @click="modal = 'find'"
      >
        <Search :size="21" /></button
      ><span class="rail-space" /><button
        class="rail-item"
        aria-label="Профиль и настройки"
        @click="openProfile"
      >
        <Settings2 :size="21" /></button
      ><button
        class="rail-avatar"
        aria-label="Открыть свой профиль"
        @click="openProfile"
      >
        {{ (profile?.display_name ?? "А")[0] }}
      </button>
    </nav>
    <aside class="chat-sidebar">
      <div class="sidebar-header">
        <span class="sidebar-eyebrow">/ твоё пространство</span>
        <div class="sidebar-title">
          <h1>Чаты<span class="title-period">.</span></h1>
          <button
            class="new-chat"
            aria-label="Найти собеседника"
            @click="modal = 'find'"
          >
            <Plus :size="21" />
          </button>
        </div>
        <label class="chat-search"
          ><Search :size="18" /><span class="sr-only">Поиск по чатам</span
          ><input
            v-model="search"
            placeholder="Поиск по чатам"
            :disabled="!demo"
        /></label>
        <div class="chat-filters">
          <button :class="{ active: filter === 'all' }" @click="filter = 'all'">
            Все чаты</button
          ><button
            :class="{ active: filter === 'unread' }"
            @click="filter = 'unread'"
          >
            Непрочитанные
          </button>
        </div>
      </div>
      <div class="chat-list">
        <button
          v-for="chat in filtered"
          :key="chat.id"
          :class="['chat-item', { active: activeId === chat.id }]"
          @click="chooseChat(chat.id)"
        >
          <span :class="['contact-avatar', chat.tint]">{{ chat.initial }}</span
          ><span class="chat-item-copy"
            ><span class="chat-item-top"
              ><strong>{{ chat.name }}</strong
              ><small>{{ chat.messages.at(-1)?.time }}</small></span
            ><span class="chat-item-bottom"
              ><span>{{ chat.preview }}</span
              ><b v-if="chat.unread">{{ chat.unread }}</b></span
            ></span
          >
        </button>
        <p v-if="demo && filtered.length === 0" class="no-results">
          Таких чатов пока нет.
        </p>
        <div v-if="!demo" class="live-list-empty">
          <img src="/fox-envelope.png" alt="Белоснежный лис с письмом" />
          <p>Здесь появятся твои разговоры.</p>
          <small>Диалоги пока готовятся на сервере.</small>
        </div>
      </div>
      <button
        class="sidebar-card grain"
        @click="demo ? router.push('/register') : (modal = 'find')"
      >
        <span>{{ demo ? "Это демо" : "Есть кого позвать?" }}</span
        ><strong>{{
          demo ? "Пора познакомиться по-настоящему" : "Найди друга по нику"
        }}</strong
        ><img
          src="/fox-sleeping.png"
          alt=""
          class="sidebar-card-fox"
        /><ArrowUpRight :size="19" />
      </button>
    </aside>
    <section class="chat-main">
      <template v-if="activeChat"
        ><header class="conversation-header">
          <button
            class="mobile-back"
            aria-label="Назад к чатам"
            @click="activeId = null"
          >
            <ArrowLeft :size="22" /></button
          ><span :class="['contact-avatar', activeChat.tint]">{{
            activeChat.initial
          }}</span>
          <div>
            <h2>{{ activeChat.name }}</h2>
            <small>{{ activeChat.online ? "в сети" : "был(а) недавно" }}</small>
          </div>
          <span class="header-space" /><img
            src="/fox-sleeping.png"
            alt="Спящий белоснежный лис"
            class="chat-fox-mini"
          /><button aria-label="Открыть поиск" @click="modal = 'find'">
            <Search :size="20" />
          </button>
        </header>
        <div class="conversation-messages">
          <div class="chat-day">Сегодня · хорошее время поговорить</div>
          <div
            v-for="message in activeChat.messages"
            :key="message.id"
            :class="['message-row', { mine: message.mine }]"
          >
            <div class="message-bubble">
              {{ message.text
              }}<time
                >{{ message.time }}<Check v-if="message.mine" :size="13"
              /></time>
            </div>
          </div>
          <div ref="messagesEnd" />
        </div>
        <form class="composer" @submit.prevent="sendMessage">
          <label class="sr-only" for="message-input">Сообщение</label
          ><input
            id="message-input"
            v-model="draft"
            placeholder="Написать сообщение…"
          /><button
            type="submit"
            aria-label="Отправить сообщение"
            :disabled="!draft.trim()"
          >
            <Send :size="20" />
          </button></form
      ></template>
      <div v-else class="empty-conversation">
        <span class="empty-top-label">{{
          demo
            ? "Демо-пространство"
            : `Привет, ${profile?.display_name ?? user?.email.split("@")[0] ?? "друг"}`
        }}</span>
        <div class="empty-center">
          <img
            src="/fox-plane.png"
            alt="Белоснежный лис ждёт первого сообщения с бумажным самолётиком"
          />
          <h2>{{ demo ? "Начнём разговор?" : "Пока тут тихо." }}</h2>
          <p>
            {{
              demo
                ? "Выбери один из чатов слева и попробуй написать."
                : "Когда появится возможность создавать диалоги, твои разговоры будут здесь."
            }}
          </p>
          <button v-if="!demo" class="pill-button" @click="modal = 'find'">
            Найти человека <ArrowUpRight :size="18" />
          </button>
        </div>
        <span class="empty-bottom-label">Свои люди. На связи.</span>
      </div>
    </section>
    <div v-if="demo" class="demo-ribbon">
      <Sparkles :size="15" /> Демо: сообщения хранятся только на этой странице.
      <RouterLink to="/register"
        >Создать аккаунт <ArrowRight :size="14"
      /></RouterLink>
    </div>
    <div v-if="modal" class="modal-backdrop" @mousedown.self="closeModal">
      <section
        class="modal-card"
        role="dialog"
        aria-modal="true"
        :aria-label="modal === 'find' ? 'Найти человека' : 'Мой профиль'"
      >
        <button class="modal-close" aria-label="Закрыть" @click="closeModal">
          <X :size="20" />
        </button>
        <template v-if="modal === 'find'"
          ><div class="modal-kicker">/ люди рядом</div>
          <h2>Найти человека</h2>
          <p class="modal-description">
            {{
              demo
                ? "В демо это только пример поиска. Войди, чтобы искать настоящие профили."
                : "Введи ник, чтобы найти профиль. Создание диалогов подключим, когда сервер будет готов."
            }}
          </p>
          <form v-if="!demo" class="lookup-form" @submit.prevent="find">
            <label for="lookup-input">Ник пользователя</label>
            <div>
              <span>@</span
              ><input
                id="lookup-input"
                v-model="lookup"
                minlength="3"
                maxlength="33"
                required
                placeholder="username"
              /><button :disabled="lookupBusy" aria-label="Искать">
                <Search :size="19" />
              </button>
            </div>
          </form>
          <p v-if="lookupError" class="form-error" role="alert">
            {{ lookupError }}
          </p>
          <div v-if="found" class="found-profile">
            <span class="contact-avatar mint">{{ found.display_name[0] }}</span>
            <div>
              <strong>{{ found.display_name }}</strong
              ><small>@{{ found.username ?? "без ника" }}</small>
            </div>
            <Check :size="19" />
          </div>
          <RouterLink v-if="demo" class="form-submit" to="/register"
            >Создать аккаунт <ArrowUpRight :size="18" /></RouterLink
          ><img
            src="/fox-envelope.png"
            alt="Белоснежный лис с письмом"
            class="modal-fox"
        /></template>
        <template v-else
          ><div class="modal-kicker">/ это ты</div>
          <h2>Мой профиль</h2>
          <div class="profile-banner grain">
            <img src="/fox-front.png" alt="Белоснежный лис смотрит прямо" />
          </div>
          <template v-if="demo"
            ><p class="modal-description">
              В демо можно заглянуть в интерфейс. Настоящий профиль появится
              после регистрации.
            </p>
            <RouterLink class="form-submit" to="/register"
              >Создать аккаунт
              <ArrowUpRight :size="18" /></RouterLink></template
          ><template v-else
            ><p class="profile-email">{{ user?.email }}</p>
            <form v-if="profile" class="profile-form" @submit.prevent="save">
              <label class="field-label"
                >Имя<input
                  v-model="editName"
                  required
                  minlength="1"
                  maxlength="64" /></label
              ><label class="field-label"
                >Ник<input
                  v-model="editUsername"
                  minlength="3"
                  maxlength="32"
                  placeholder="Как тебя найти" /></label
              ><label class="field-label"
                >О себе<textarea
                  v-model="editBio"
                  maxlength="255"
                  placeholder="Пара слов о себе"
                />
              </label>
              <p v-if="saveError" class="form-error" role="alert">
                {{ saveError }}
              </p>
              <button class="form-submit" :disabled="saveBusy">
                {{ saveBusy ? "Сохраняем…" : "Сохранить" }} <Check :size="18" />
              </button>
            </form>
            <p v-else class="form-pending">
              Не удалось загрузить профиль. Повтори попытку позже.
            </p></template
          ><button class="logout-button" @click="signOut">
            {{ demo ? "На главную" : "Выйти из аккаунта" }}
            <ChevronRight :size="17" /></button
        ></template>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { ArrowLeft, ArrowUpRight } from "@lucide/vue";
import { getCurrentUser, humanError, login, register } from "../api";

const props = defineProps<{ kind: "login" | "register" }>();
const router = useRouter();
const isRegister = computed(() => props.kind === "register");
const email = ref("");
const password = ref("");
const confirm = ref("");
const busy = ref(false);
const error = ref("");
const pending = ref(false);
let registrationKey = crypto.randomUUID();

watch(
  () => props.kind,
  () => {
    error.value = "";
    pending.value = false;
    registrationKey = crypto.randomUUID();
  },
);
function resetKey() {
  pending.value = false;
  registrationKey = crypto.randomUUID();
}

async function submit() {
  error.value = "";
  if (isRegister.value && password.value !== confirm.value) {
    error.value = "Пароли не совпадают.";
    return;
  }
  busy.value = true;
  try {
    if (isRegister.value) {
      const result = await register(
        email.value.trim(),
        password.value,
        registrationKey,
      );
      if (result.status === 202) {
        pending.value = true;
        return;
      }
    }
    await login(email.value.trim(), password.value);
    await getCurrentUser();
    await router.push("/app");
  } catch (cause) {
    error.value = humanError(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="auth-page">
    <aside
      :class="['auth-scene', 'grain', { 'auth-scene-register': isRegister }]"
    >
      <RouterLink
        class="brand brand-light"
        to="/"
        aria-label="Андрюха — на главную"
        >андрюха<span class="brand-dot">.</span></RouterLink
      >
      <div class="auth-scene-copy">
        <p class="eyebrow">
          <span class="eyebrow-square" />
          {{ isRegister ? "Добро пожаловать" : "Свои рядом" }}
        </p>
        <h1 v-if="isRegister">Давай<br />знакомиться.</h1>
        <h1 v-else>Уже почти<br />дома.</h1>
        <p>
          {{
            isRegister
              ? "Хорошие разговоры начинаются с простого привет."
              : "Заходи. Твои люди где-то совсем рядом."
          }}
        </p>
      </div>
      <img
        :src="isRegister ? '/fox-envelope.png' : '/fox-front.png'"
        :alt="
          isRegister
            ? 'Белоснежный лис держит коралловый конверт'
            : 'Белоснежный лис смотрит прямо на вас'
        "
        class="auth-scene-fox"
      />
      <small class="auth-scene-foot">Ближе, даже издалека.</small>
    </aside>
    <section class="auth-content">
      <RouterLink class="back-link" to="/"
        ><ArrowLeft :size="18" /> На главную</RouterLink
      >
      <div class="auth-card">
        <p class="eyebrow dark-eyebrow">
          <span class="eyebrow-square" /> Твой уголок интернета
        </p>
        <h2>{{ isRegister ? "Рады знакомству" : "С возвращением" }}</h2>
        <p class="auth-subtitle">
          {{
            isRegister
              ? "Создай аккаунт — а дальше разберёмся вместе."
              : "Твои разговоры продолжаются здесь."
          }}
        </p>
        <form @submit.prevent="submit">
          <label class="field-label"
            >Почта<input
              v-model="email"
              type="email"
              autocomplete="email"
              required
              placeholder="you@example.com"
              @input="resetKey"
          /></label>
          <label class="field-label"
            >Пароль<input
              v-model="password"
              type="password"
              :autocomplete="isRegister ? 'new-password' : 'current-password'"
              :minlength="isRegister ? 8 : 1"
              maxlength="128"
              required
              :placeholder="
                isRegister ? 'Минимум 8 символов' : 'Введите пароль'
              "
              @input="resetKey"
          /></label>
          <label v-if="isRegister" class="field-label"
            >Повтори пароль<input
              v-model="confirm"
              type="password"
              autocomplete="new-password"
              required
              placeholder="Ещё раз, для уверенности"
          /></label>
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>
          <p v-if="pending" class="form-pending" role="status">
            Аккаунт уже создаётся. Подождите немного и повторите запрос той же
            кнопкой.
          </p>
          <button type="submit" class="form-submit" :disabled="busy">
            {{
              busy
                ? "Подождите…"
                : pending
                  ? "Проверить создание"
                  : isRegister
                    ? "Создать аккаунт"
                    : "Войти"
            }}
            <ArrowUpRight :size="19" />
          </button>
        </form>
        <p class="auth-switch">
          {{ isRegister ? "Уже знакомы?" : "Впервые здесь?" }}
          <RouterLink :to="isRegister ? '/login' : '/register'">{{
            isRegister ? "Войти" : "Познакомиться"
          }}</RouterLink>
        </p>
      </div>
      <span class="auth-aside-note"
        >Все разговоры начинаются с первого слова.</span
      >
    </section>
  </main>
</template>

(() => {
  const picker = document.getElementById("photoFiles");
  const button = document.getElementById("uploadBtn");
  const status = document.getElementById("uploadStatus");
  const progress = document.getElementById("uploadProgress");
  if (!picker || !button || !status || !progress) return;

  const MAX_EDGE = 2560;
  const JPEG_QUALITY = 0.84;

  async function compressPhoto(file) {
    let bitmap;
    try {
      if ("createImageBitmap" in window) {
        bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      }
    } catch (_) { /* Fall back to an HTML image for browsers without bitmap support. */ }

    let source = bitmap;
    if (!source) {
      source = await new Promise((resolve, reject) => {
        const image = new Image();
        const objectUrl = URL.createObjectURL(file);
        image.onload = () => { URL.revokeObjectURL(objectUrl); resolve(image); };
        image.onerror = () => { URL.revokeObjectURL(objectUrl); reject(new Error("Could not read " + file.name)); };
        image.src = objectUrl;
      });
    }

    const width = source.width || source.naturalWidth;
    const height = source.height || source.naturalHeight;
    const scale = Math.min(1, MAX_EDGE / Math.max(width, height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const context = canvas.getContext("2d", { alpha: false });
    context.drawImage(source, 0, 0, canvas.width, canvas.height);
    if (bitmap && bitmap.close) bitmap.close();

    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob(result => result ? resolve(result) : reject(new Error("Image compression failed for " + file.name)), "image/jpeg", JPEG_QUALITY);
    });
    return blob;
  }

  button.addEventListener("click", async () => {
    const files = Array.from(picker.files || []);
    if (!files.length) { status.textContent = "Please choose one or more photos first."; return; }
    if (!window.supabase || !window.SUPABASE_URL || !window.SUPABASE_ANON_KEY) {
      status.textContent = "Upload setup is incomplete. Check the Supabase public key setting in Render."; return;
    }

    button.disabled = true;
    picker.disabled = true;
    progress.style.display = "block";
    progress.value = 0;
    let uploaded = 0;
    let savedBytes = 0;
    const client = window.supabase.createClient(window.SUPABASE_URL, window.SUPABASE_ANON_KEY);

    try {
      for (let i = 0; i < files.length; i++) {
        const original = files[i];
        if (!/^image\/(jpeg|png|webp)$/i.test(original.type)) {
          throw new Error(original.name + " is not a supported JPG, PNG, or WebP image.");
        }
        status.textContent = "Compressing " + (i + 1) + " of " + files.length + ": " + original.name;
        const compressed = await compressPhoto(original);
        savedBytes += Math.max(0, original.size - compressed.size);

        status.textContent = "Preparing secure upload for " + original.name;
        const tokenResponse = await fetch("/api/admin/event/" + encodeURIComponent(window.EVENT_SLUG) + "/upload-token", {
          method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: "{}"
        });
        const tokenData = await tokenResponse.json();
        if (!tokenResponse.ok) throw new Error(tokenData.error || "Could not prepare a secure upload.");

        status.textContent = "Uploading " + (i + 1) + " of " + files.length + ": " + original.name;
        const result = await client.storage.from(tokenData.bucket).uploadToSignedUrl(
          tokenData.path, tokenData.token, compressed,
          { contentType: "image/jpeg", upsert: false }
        );
        if (result.error) throw result.error;

        const completeResponse = await fetch("/api/admin/event/" + encodeURIComponent(window.EVENT_SLUG) + "/photos/complete", {
          method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: tokenData.path })
        });
        const completeData = await completeResponse.json();
        if (!completeResponse.ok) throw new Error(completeData.error || "The photo uploaded but could not be added to the gallery.");

        uploaded++;
        progress.value = Math.round((uploaded / files.length) * 100);
        status.textContent = "Uploaded " + uploaded + " of " + files.length + " photos.";
      }
      const mb = (savedBytes / (1024 * 1024)).toFixed(1);
      status.textContent = "Finished: " + uploaded + " photo(s) uploaded. Approximately " + mb + " MB saved by compression. Refreshing gallery…";
      window.location.reload();
    } catch (error) {
      console.error(error);
      status.textContent = "Upload stopped after " + uploaded + " photo(s): " + (error.message || "Unknown error") + ". You can retry the remaining photos; completed uploads are kept.";
    } finally {
      button.disabled = false;
      picker.disabled = false;
    }
  });

  const importButton = document.getElementById("importRootBtn");
  const importStatus = document.getElementById("importRootStatus");
  importButton?.addEventListener("click", async () => {
    if (!window.confirm("Attach existing image files from the root of your wedding-photos bucket to this event? Existing storage files will not be changed or deleted.")) return;
    importButton.disabled = true;
    importStatus.textContent = "Checking existing Supabase photos…";
    try {
      const response = await fetch("/api/admin/event/" + encodeURIComponent(window.EVENT_SLUG) + "/photos/import-root", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: "{}"
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not import existing photos.");
      importStatus.textContent = "Added " + data.imported + " existing photo(s) to this event. Refreshing gallery…";
      window.location.reload();
    } catch (error) {
      importStatus.textContent = "Import failed: " + (error.message || "Unknown error");
      importButton.disabled = false;
    }
  });
})();
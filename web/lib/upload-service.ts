import { ref, uploadBytes, getDownloadURL } from "firebase/storage";
import { doc, setDoc } from "firebase/firestore";
import { db, storage } from "@/utils/firebase.browser";

export const MAX_FILE_SIZE_MB = 15;

export async function uploadPresentationFile(
  file: File,
  sessionId: string,
): Promise<string> {
  // Pre-flight validation
  if (file.type !== "application/pdf") {
    throw new Error("Invalid file format. Please upload a PDF.");
  }

  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    throw new Error(
      `File is too large. Maximum size is ${MAX_FILE_SIZE_MB}MB.`,
    );
  }

  try {
    const storageRef = ref(storage, `pdfs/${sessionId}/${file.name}`);

    // Upload the file
    await uploadBytes(storageRef, file);
    const downloadUrl = await getDownloadURL(storageRef);

    // Create the Firestore document to trigger the UI update and Python agents
    await setDoc(doc(db, "presentations", sessionId), {
      status: "generating",
      pdfUrl: downloadUrl,
      fileName: file.name,
      createdAt: new Date().toISOString(),
    });

    return downloadUrl;
  } catch (error: any) {
    console.error("Firebase Upload Error:", error);
    throw new Error(
      "Failed to upload the document to the server. Please try again.",
    );
  }
}

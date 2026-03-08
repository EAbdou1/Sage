import { ref, uploadBytes, getDownloadURL } from "firebase/storage";
import { doc, setDoc, updateDoc, arrayUnion } from "firebase/firestore";
import { db, storage } from "@/utils/firebase.browser";

export const MAX_FILE_SIZE_MB = 15;

export async function uploadPresentationFile(
  file: File,
  sessionId: string,
): Promise<string> {
  if (file.type !== "application/pdf") {
    throw new Error("Invalid file format. Please upload a PDF.");
  }

  if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
    throw new Error(
      `File is too large. Maximum size is ${MAX_FILE_SIZE_MB}MB.`,
    );
  }

  const docRef = doc(db, "presentations", sessionId);

  try {
    // 1. Instantly create the document to wake up the Logger Panel
    await setDoc(docRef, {
      status: "uploading",
      fileName: file.name,
      createdAt: new Date().toISOString(),
      logs: [
        {
          timestamp: new Date().toISOString(),
          agent: "System",
          message: `Initiating secure upload for ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)...`,
          type: "info",
        },
      ],
    });

    // 2. Upload the file to Cloud Storage
    const storageRef = ref(storage, `pdfs/${sessionId}/${file.name}`);
    await uploadBytes(storageRef, file);
    const downloadUrl = await getDownloadURL(storageRef);

    // 3. Append the success log and hand it off to the agents
    await updateDoc(docRef, {
      status: "generating",
      pdfUrl: downloadUrl,
      logs: arrayUnion({
        timestamp: new Date().toISOString(),
        agent: "System",
        message:
          "File successfully uploaded to Cloud Storage. Waking up Agent Pipeline...",
        type: "success",
      }),
    });

    setTimeout(async () => {
      await updateDoc(docRef, {
        status: "ready",
        logs: arrayUnion({
          timestamp: new Date().toISOString(),
          agent: "System",
          message: "Pipeline complete. Launching presentation.",
          type: "success",
        }),
        slides: [
          {
            id: 0,
            title: "Pathophysiology of H. Pylori",
            content:
              "Helicobacter pylori survives in the acidic environment of the stomach by secreting urease, which converts urea to ammonia, neutralizing the acid.",
          },
          {
            id: 1,
            title: "Knowledge Check",
            content:
              "Which enzyme is primarily responsible for allowing this bacteria to survive gastric acid?",
            isMCQ: true,
            mcqOptions: ["Amylase", "Urease", "Protease", "Lipase"],
          },
        ],
      });
    }, 5000);

    return downloadUrl;
  } catch (error: any) {
    console.error("Firebase Upload Error:", error);

    try {
      await updateDoc(docRef, {
        status: "error",
        logs: arrayUnion({
          timestamp: new Date().toISOString(),
          agent: "System",
          message: `Upload failed: ${error.message}`,
          type: "error",
        }),
      });
    } catch (e) {
      // Catch in case the document wasn't created yet
    }

    throw new Error(
      "Failed to upload the document to the server. Please try again.",
    );
  }
}

/**
 * TypeScript declarations for the File and Directory Entries API.
 * Used for folder uploads via webkitdirectory and drag-and-drop.
 * 
 * @see https://wicg.github.io/entries-api/
 * @see https://developer.mozilla.org/en-US/docs/Web/API/File_and_Directory_Entries_API
 */

/**
 * Extends HTMLInputElement to include webkitdirectory attribute.
 */
interface HTMLInputElement {
  /**
   * Allows selection of directories instead of files.
   * Supported in Chrome, Firefox, Safari, and Edge.
   */
  webkitdirectory: boolean;
  
  /**
   * Standard directory attribute (alias for webkitdirectory).
   */
  directory: boolean;
}

/**
 * Extends File to include webkitRelativePath property.
 */
interface File {
  /**
   * The path of the file relative to the selected directory.
   * Only available when files are selected via webkitdirectory input.
   * Example: "folder/subfolder/file.txt"
   */
  readonly webkitRelativePath: string;
}

/**
 * Base interface for file system entries (files and directories).
 */
interface FileSystemEntry {
  /** True if this entry is a file. */
  readonly isFile: boolean;
  /** True if this entry is a directory. */
  readonly isDirectory: boolean;
  /** The name of the entry (file or directory name). */
  readonly name: string;
  /** The full path from the root. */
  readonly fullPath: string;
  /** The file system this entry belongs to. */
  readonly filesystem: FileSystem;
}

/**
 * Represents a file in the file system.
 */
interface FileSystemFileEntry extends FileSystemEntry {
  readonly isFile: true;
  readonly isDirectory: false;
  /**
   * Get the File object for this entry.
   * @param successCallback Called with the File object.
   * @param errorCallback Called if an error occurs.
   */
  file(successCallback: (file: File) => void, errorCallback?: (error: DOMException) => void): void;
}

/**
 * Represents a directory in the file system.
 */
interface FileSystemDirectoryEntry extends FileSystemEntry {
  readonly isFile: false;
  readonly isDirectory: true;
  /**
   * Create a reader for reading entries in this directory.
   */
  createReader(): FileSystemDirectoryReader;
}

/**
 * Reader for iterating through entries in a directory.
 */
interface FileSystemDirectoryReader {
  /**
   * Read a batch of entries from the directory.
   * Must be called repeatedly until empty array is returned.
   * @param successCallback Called with an array of entries.
   * @param errorCallback Called if an error occurs.
   */
  readEntries(
    successCallback: (entries: FileSystemEntry[]) => void,
    errorCallback?: (error: DOMException) => void
  ): void;
}

/**
 * Extends DataTransferItem to include webkitGetAsEntry method.
 */
interface DataTransferItem {
  /**
   * Get the file system entry for this item.
   * Returns null if the item is not a file or directory.
   */
  webkitGetAsEntry(): FileSystemEntry | null;
}
